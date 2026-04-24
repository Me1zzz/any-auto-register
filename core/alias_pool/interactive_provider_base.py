from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Mapping, Sequence

from core.alias_pool.base import AliasEmailLease
from core.alias_pool.base import AliasSourceState
from core.alias_pool.interactive_provider_models import (
    AliasCreatedRecord,
    AliasDomainOption,
    AuthenticatedProviderContext,
    VerificationRequirement,
)
from core.alias_pool.interactive_provider_state import InteractiveProviderState
from core.alias_pool.interactive_state_repository import InteractiveStateRepository
from core.alias_pool.provider_contracts import (
    AliasAccountIdentity,
    AliasAutomationTestPolicy,
    AliasAutomationTestResult,
    AliasProviderBootstrapContext,
    AliasProviderCapture,
    AliasProviderFailure,
    AliasProviderSourceSpec,
    AliasProviderStage,
)


_REQUIREMENT_STAGE_CODES = {
    "account_email": "verify_account_email",
    "forwarding_email": "verify_forwarding_email",
    "request_magic_link": "request_magic_link",
    "magic_link_login": "consume_magic_link",
}


class InteractiveAliasProviderBase:
    source_kind = "interactive_alias_provider"

    def __init__(self, *, spec: AliasProviderSourceSpec, context: AliasProviderBootstrapContext):
        self._spec = spec
        self._context = context
        self.source_id = spec.source_id
        self._state_repository = self._build_state_repository()
        self._state = AliasSourceState.IDLE
        self._account_selection_state: InteractiveProviderState | None = None

    @property
    def provider_type(self) -> str:
        return self.source_kind

    def state(self) -> AliasSourceState:
        return self._state

    def load_into(self, pool_manager) -> None:
        self.ensure_available(
            pool_manager,
            minimum_count=max(int(self._spec.desired_alias_count or 0), 1),
        )

    def ensure_available(self, pool_manager, *, minimum_count: int = 1) -> None:
        requested = max(int(minimum_count or 0), 1)
        state = self._state_repository.load()
        selection_state_before = self._account_selection_state
        self._account_selection_state = state
        has_multi_account_state = bool(self._build_accounts_state(state))
        known_aliases_before = self._flatten_known_aliases(state)
        cap = max(int(self._spec.desired_alias_count or 0), 1)
        try:
            if has_multi_account_state:
                if self._all_accounts_exhausted(state):
                    self._state = AliasSourceState.EXHAUSTED
                    return
            elif len(known_aliases_before) >= cap:
                self._state = AliasSourceState.EXHAUSTED
                return

            self._state = AliasSourceState.ACTIVE
            target_total = (
                len(known_aliases_before) + requested
                if has_multi_account_state
                else min(cap, len(known_aliases_before) + requested)
            )

            if has_multi_account_state:
                self._ensure_available_across_accounts(
                    pool_manager,
                    state=state,
                    target_total=target_total,
                )
            else:
                context = self.ensure_authenticated_context("task_pool")
                context = self._seed_context_from_state(context, state)

                for requirement in self.resolve_verification_requirements(context):
                    context = self.satisfy_verification_requirement(requirement, context)

                domains = list(self.discover_alias_domains(context))
                context = replace(context, domain_options=domains)

                aliases = self._dedupe_alias_items(
                    [{"email": email} for email in known_aliases_before]
                    + [
                        dict(item)
                        for item in list(self.list_existing_aliases(context))
                        if isinstance(item, dict)
                    ]
                )

                creation_attempt_count = len(aliases)
                stalled_attempt_count = 0
                max_stalled_attempts = max(target_total, 1)
                while len(aliases) < target_total and stalled_attempt_count < max_stalled_attempts:
                    previous_alias_count = len(aliases)
                    creation_attempt_count += 1
                    domain = self.pick_domain_option(domains, creation_attempt_count)
                    created = self.create_alias(
                        context=context,
                        domain=domain,
                        alias_index=creation_attempt_count,
                    )
                    aliases.append({"email": created.email, **dict(created.metadata or {})})
                    aliases = self._dedupe_alias_items(aliases)
                    if len(aliases) == previous_alias_count:
                        stalled_attempt_count += 1
                        continue
                    stalled_attempt_count = 0

                self._update_state_snapshot(
                    state,
                    context=context,
                    domains=domains,
                    aliases=aliases,
                    timeline=[],
                    capture_summary=[],
                )

            self._state_repository.save(state)

            self._add_new_alias_leases(
                pool_manager,
                state=state,
                known_aliases_before=known_aliases_before,
            )

            known_aliases_after = self._flatten_known_aliases(state)
            if has_multi_account_state:
                self._state = (
                    AliasSourceState.EXHAUSTED
                    if self._all_accounts_exhausted(state)
                    else AliasSourceState.ACTIVE
                )
            else:
                self._state = (
                    AliasSourceState.EXHAUSTED
                    if len(known_aliases_after) >= cap
                    else AliasSourceState.ACTIVE
                )
        except Exception:
            self._state = AliasSourceState.FAILED
            raise
        finally:
            self._account_selection_state = selection_state_before

    def run_alias_generation_test(self, policy: AliasAutomationTestPolicy) -> AliasAutomationTestResult:
        timeline: list[AliasProviderStage] = []

        def record(code: str, label: str, status: str, detail: str = "") -> None:
            timeline.append(AliasProviderStage(code=code, label=label, status=status, detail=detail))

        def update_last(status: str, detail: str = "") -> None:
            if not timeline:
                return
            last = timeline[-1]
            timeline[-1] = AliasProviderStage(
                code=last.code,
                label=last.label,
                status=status,
                detail=detail,
            )

        state = None

        selection_state_before = self._account_selection_state
        try:
            if policy.fresh_service_account:
                state = self._state_repository.new_state()
            else:
                state = self._state_repository.load()
            if not policy.persist_state:
                state = deepcopy(state)
            self._account_selection_state = state
            has_multi_account_state = bool(self._build_accounts_state(state))

            if has_multi_account_state:
                target = max(int(policy.minimum_alias_count or 0), int(self._spec.desired_alias_count or 0), 1)
                record("session_ready", "Session ready", "completed")
                record("discover_alias_domains", "Discover alias domains", "pending")
                record("list_aliases", "List existing aliases", "pending")
                record("create_aliases", "Create aliases", "pending")
                context, domains = self._preview_aliases_across_accounts(
                    state=state,
                    target_total=target,
                )
                aliases = [{"email": email} for email in self._flatten_known_aliases(state)]
                timeline[-3] = AliasProviderStage(
                    code=timeline[-3].code,
                    label=timeline[-3].label,
                    status="completed",
                    detail=f"found {len(domains)} domain options",
                )
                timeline[-2] = AliasProviderStage(
                    code=timeline[-2].code,
                    label=timeline[-2].label,
                    status="completed",
                    detail=f"found {len(aliases)} aliases",
                )
                update_last("completed", detail=f"prepared {len(aliases)} aliases")
                record("aliases_ready", "Aliases ready", "completed", detail=f"prepared {len(aliases)} aliases")

                capture_summary = self._capture_summary_for_policy(policy)
                if policy.persist_state:
                    record("save_state", "Save preview state", "pending")
                    update_last("completed")
                    self._update_state_preview_metadata(
                        state,
                        timeline=timeline,
                        capture_summary=capture_summary,
                    )
                    self._state_repository.save(state)
                else:
                    self._update_state_preview_metadata(
                        state,
                        timeline=timeline,
                        capture_summary=capture_summary,
                    )

                return AliasAutomationTestResult(
                    provider_type=self.provider_type,
                    source_id=self.source_id,
                    account_identity=AliasAccountIdentity(
                        service_account_email=context.service_account_email,
                        confirmation_inbox_email=context.confirmation_inbox_email,
                        real_mailbox_email=context.real_mailbox_email,
                        service_password=context.service_password,
                        username=context.username,
                    ),
                    aliases=aliases[:target],
                    current_stage=timeline[-1],
                    stage_timeline=timeline,
                    failure=AliasProviderFailure(),
                    capture_summary=capture_summary,
                    logs=[],
                    ok=True,
                    error="",
                )

            context = self.ensure_authenticated_context("alias_test")
            if not policy.fresh_service_account:
                context = self._seed_context_from_state(context, state)
            record("session_ready", "会话已就绪", "completed")

            for requirement in self.resolve_verification_requirements(context):
                stage_code = _REQUIREMENT_STAGE_CODES.get(requirement.kind, requirement.kind)
                record(stage_code, requirement.label, "pending")
                context = self.satisfy_verification_requirement(requirement, context)
                update_last("completed")

            record("discover_alias_domains", "发现可用域名", "pending")
            domains = list(self.discover_alias_domains(context))
            context = replace(context, domain_options=domains)
            update_last("completed", detail=f"找到 {len(domains)} 个域名选项")

            record("list_aliases", "列出现有别名", "pending")
            aliases = [
                dict(item)
                for item in list(self.list_existing_aliases(context))
                if isinstance(item, dict)
            ]
            aliases = self._dedupe_alias_items(aliases)
            update_last("completed", detail=f"找到 {len(aliases)} 个别名")

            target = max(int(policy.minimum_alias_count or 0), int(self._spec.desired_alias_count or 0), 1)
            record("create_aliases", "创建别名", "pending")
            creation_attempt_count = len(aliases)
            stalled_attempt_count = 0
            max_stalled_attempts = max(target, 1)
            while len(aliases) < target and stalled_attempt_count < max_stalled_attempts:
                previous_alias_count = len(aliases)
                creation_attempt_count += 1
                alias_index = creation_attempt_count
                domain = self.pick_domain_option(domains, alias_index)
                created = self.create_alias(context=context, domain=domain, alias_index=alias_index)
                aliases.append({"email": created.email, **dict(created.metadata or {})})
                aliases = self._dedupe_alias_items(aliases)
                if len(aliases) == previous_alias_count:
                    stalled_attempt_count += 1
                    continue
                stalled_attempt_count = 0

            update_last("completed", detail=f"预览共 {len(aliases)} 个别名")
            record("aliases_ready", "别名预览已生成", "completed", detail=f"预览共 {len(aliases)} 个别名")

            capture_summary = self._capture_summary_for_policy(policy)

            if policy.persist_state:
                record("save_state", "保存预览状态", "pending")
                update_last("completed")
                self._update_state_snapshot(
                    state,
                    context=context,
                    domains=domains,
                    aliases=aliases,
                    timeline=timeline,
                    capture_summary=capture_summary,
                )
                self._state_repository.save(state)
            else:
                self._update_state_snapshot(
                    state,
                    context=context,
                    domains=domains,
                    aliases=aliases,
                    timeline=timeline,
                    capture_summary=capture_summary,
                )

            return AliasAutomationTestResult(
                provider_type=self.provider_type,
                source_id=self.source_id,
                account_identity=AliasAccountIdentity(
                    service_account_email=context.service_account_email,
                    confirmation_inbox_email=context.confirmation_inbox_email,
                    real_mailbox_email=context.real_mailbox_email,
                    service_password=context.service_password,
                    username=context.username,
                ),
                aliases=aliases[:target],
                current_stage=timeline[-1],
                stage_timeline=timeline,
                failure=AliasProviderFailure(),
                capture_summary=capture_summary,
                logs=[],
                ok=True,
                error="",
            )
        except Exception as exc:
            if timeline:
                failed_stage = timeline[-1]
                timeline[-1] = AliasProviderStage(
                    code=failed_stage.code,
                    label=failed_stage.label,
                    status="failed",
                    detail=str(exc),
                )
                current_stage = timeline[-1]
            else:
                current_stage = AliasProviderStage(code="session_ready", label="", status="failed", detail=str(exc))
                timeline.append(current_stage)

            return AliasAutomationTestResult(
                provider_type=self.provider_type,
                source_id=self.source_id,
                current_stage=current_stage,
                stage_timeline=timeline,
                failure=AliasProviderFailure(
                    stage_code=current_stage.code,
                    stage_label=current_stage.label,
                    reason=str(exc),
                    retryable=True,
                ),
                capture_summary=self._capture_summary_for_policy(policy),
                logs=[str(exc)],
                ok=False,
                error=str(exc),
            )
        finally:
            self._account_selection_state = selection_state_before

    def _build_state_repository(self) -> InteractiveStateRepository:
        state_key = self._spec.state_key or self.source_id
        store_factory = getattr(self._context, "state_store_factory", None)
        store = store_factory(state_key) if callable(store_factory) else None
        return InteractiveStateRepository(store=store, state_key=state_key)

    def _capture_summary_for_policy(self, policy: AliasAutomationTestPolicy) -> list[AliasProviderCapture]:
        if not policy.capture_enabled:
            return []
        return self.build_capture_summary()

    def _ensure_available_across_accounts(
        self,
        pool_manager,
        *,
        state: InteractiveProviderState,
        target_total: int,
        mode: str = "task_pool",
    ) -> tuple[AuthenticatedProviderContext | None, list[AliasDomainOption]]:
        last_context: AuthenticatedProviderContext | None = None
        last_domains: list[AliasDomainOption] = []
        while len(self._flatten_known_aliases(state)) < target_total:
            account = self._select_next_available_account(state)
            if account is None:
                break

            context = self.ensure_authenticated_context(mode)
            context = self._seed_context_from_state(context, state)

            for requirement in self.resolve_verification_requirements(context):
                context = self.satisfy_verification_requirement(requirement, context)

            domains = list(self.discover_alias_domains(context))
            context = replace(context, domain_options=domains)
            last_context = context
            last_domains = domains

            account_aliases = self._dedupe_alias_items(
                [{"email": email} for email in self._account_known_aliases(account)]
                + [
                    dict(item)
                    for item in list(self.list_existing_aliases(context))
                    if isinstance(item, Mapping)
                ]
            )

            if self._account_is_full(self._alias_values_from_items(account_aliases)):
                self._update_state_snapshot(
                    state,
                    context=context,
                    domains=domains,
                    aliases=account_aliases,
                    timeline=[],
                    capture_summary=[],
                )
                self._mark_account_exhausted(state, str(account.get("email") or ""))
                continue

            creation_attempt_count = len(account_aliases)
            stalled_attempt_count = 0
            max_stalled_attempts = max(target_total, 1)
            persisted_total = len(self._flatten_known_aliases(state))
            persisted_account_total = len(self._account_known_aliases(account))
            other_account_total = max(persisted_total - persisted_account_total, 0)
            while (
                other_account_total + len(self._alias_values_from_items(account_aliases)) < target_total
                and stalled_attempt_count < max_stalled_attempts
                and not self._account_is_full(self._alias_values_from_items(account_aliases))
            ):
                previous_alias_count = len(account_aliases)
                creation_attempt_count += 1
                domain = self.pick_domain_option(domains, creation_attempt_count)
                created = self.create_alias(
                    context=context,
                    domain=domain,
                    alias_index=creation_attempt_count,
                )
                account_aliases.append({"email": created.email, **dict(created.metadata or {})})
                account_aliases = self._dedupe_alias_items(account_aliases)
                if len(account_aliases) == previous_alias_count:
                    stalled_attempt_count += 1
                    continue
                stalled_attempt_count = 0

            self._update_state_snapshot(
                state,
                context=context,
                domains=domains,
                aliases=account_aliases,
                timeline=[],
                capture_summary=[],
            )
            if self._account_is_full(self._alias_values_from_items(account_aliases)):
                self._mark_account_exhausted(state, str(account.get("email") or ""))
            elif stalled_attempt_count >= max_stalled_attempts:
                self._mark_account_exhausted(state, str(account.get("email") or ""))
                continue
        return last_context, last_domains

    def _configured_accounts(self) -> list[dict[str, str]]:
        configured_accounts: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in list(self._spec.provider_config.get("accounts") or []):
            if not isinstance(item, Mapping):
                continue
            email = str(item.get("email") or "").strip().lower()
            if not email or email in seen:
                continue
            seen.add(email)
            password = str(item.get("password") or email).strip() or email
            label = str(item.get("label") or item.get("username") or email.split("@")[0]).strip()
            configured_accounts.append({"email": email, "password": password, "label": label or email})
        return configured_accounts

    def _single_account_alias_cap(self) -> int:
        raw_value = self._spec.provider_config.get("single_account_alias_count")
        try:
            return max(int(raw_value or 0), 0)
        except (TypeError, ValueError):
            return 0

    def _build_accounts_state(self, state: InteractiveProviderState) -> list[dict[str, object]]:
        configured_accounts = self._configured_accounts()
        if not configured_accounts:
            state.accounts_state = []
            return []

        persisted_by_email: dict[str, dict[str, object]] = {}
        for item in list(state.accounts_state or []):
            if not isinstance(item, Mapping):
                continue
            email = str(item.get("email") or "").strip().lower()
            if not email:
                continue
            persisted_by_email[email] = dict(item)

        legacy_email = str(state.active_account_email or state.service_account_email or "").strip().lower()
        if not legacy_email and configured_accounts:
            legacy_email = configured_accounts[0]["email"]

        accounts_state: list[dict[str, object]] = []
        for account in configured_accounts:
            email = account["email"]
            persisted = dict(persisted_by_email.get(email) or {})
            if not persisted and email == legacy_email and self._has_legacy_account_state(state):
                persisted = self._legacy_account_state_item(state, account)

            known_aliases = self._dedupe_alias_values(list(persisted.get("known_aliases") or []))
            account_state = {
                "email": email,
                "password": str(persisted.get("password") or account["password"]).strip() or account["password"],
                "label": str(persisted.get("label") or persisted.get("username") or account["label"]).strip()
                or account["label"],
                "service_account_email": email,
                "confirmation_inbox_email": str(persisted.get("confirmation_inbox_email") or "").strip().lower(),
                "real_mailbox_email": str(persisted.get("real_mailbox_email") or "").strip().lower(),
                "service_password": str(persisted.get("service_password") or account["password"]).strip() or account["password"],
                "username": str(persisted.get("username") or account["label"]).strip() or account["label"],
                "session_state": dict(persisted.get("session_state") or {}),
                "domain_options": self._normalize_domain_state_items(persisted.get("domain_options")),
                "known_aliases": known_aliases,
                "exhausted": bool(persisted.get("exhausted")),
            }
            if self._account_is_full(known_aliases):
                account_state["exhausted"] = True
            accounts_state.append(account_state)

        state.accounts_state = accounts_state
        selected_account = self._find_account_state_item(
            state,
            state.active_account_email or state.service_account_email,
        )
        if selected_account is None and accounts_state:
            selected_account = next(
                (
                    item
                    for item in accounts_state
                    if not bool(item.get("exhausted")) and not self._account_is_full(self._account_known_aliases(item))
                ),
                accounts_state[0],
            )
        if selected_account is not None:
            self._set_active_account(state, str(selected_account.get("email") or ""))
        return accounts_state

    def _select_next_available_account(self, state: InteractiveProviderState) -> dict[str, object] | None:
        accounts_state = self._build_accounts_state(state)
        if not accounts_state:
            return None

        active_account = self._find_account_state_item(state, state.active_account_email)
        if (
            active_account is not None
            and not bool(active_account.get("exhausted"))
            and not self._account_is_full(self._account_known_aliases(active_account))
        ):
            self._set_active_account(state, str(active_account.get("email") or ""))
            return active_account

        start_index = -1
        active_email = str(state.active_account_email or "").strip().lower()
        for index, item in enumerate(accounts_state):
            if str(item.get("email") or "").strip().lower() == active_email:
                start_index = index
                break

        search_order = (
            list(range(start_index + 1, len(accounts_state))) + list(range(0, start_index + 1))
            if start_index >= 0
            else list(range(len(accounts_state)))
        )
        for index in search_order:
            candidate = accounts_state[index]
            if bool(candidate.get("exhausted")):
                continue
            if self._account_is_full(self._account_known_aliases(candidate)):
                candidate["exhausted"] = True
                continue
            self._set_active_account(state, str(candidate.get("email") or ""))
            return candidate

        return None

    def _mark_account_exhausted(self, state: InteractiveProviderState, account_email: str) -> None:
        normalized_email = str(account_email or "").strip().lower()
        if not normalized_email:
            return
        for item in self._build_accounts_state(state):
            email = str(item.get("email") or "").strip().lower()
            if email != normalized_email:
                continue
            item["exhausted"] = True
            break

        next_account = self._select_next_available_account(state)
        if next_account is None:
            self._set_active_account(state, normalized_email)

    def _flatten_known_aliases(self, state: InteractiveProviderState) -> list[str]:
        if state.accounts_state:
            flattened: list[str] = []
            for item in list(state.accounts_state or []):
                if not isinstance(item, Mapping):
                    continue
                flattened.extend(self._account_known_aliases(item))
            state.known_aliases = self._dedupe_alias_values(flattened)
            return list(state.known_aliases)
        state.known_aliases = self._dedupe_alias_values(list(state.known_aliases or []))
        return list(state.known_aliases)

    def _preview_aliases_across_accounts(
        self,
        *,
        state: InteractiveProviderState,
        target_total: int,
    ) -> tuple[AuthenticatedProviderContext, list[AliasDomainOption]]:
        preview_target_total = max(len(self._flatten_known_aliases(state)), target_total)
        context, domains = self._ensure_available_across_accounts(
            _PreviewPoolManager(),
            state=state,
            target_total=preview_target_total,
            mode="alias_test",
        )
        if context is None:
            account = self._select_next_available_account(state)
            if account is None:
                raise RuntimeError(f"{self.provider_type} provider has no remaining available account")
            context = self.ensure_authenticated_context("alias_test")
            context = self._seed_context_from_state(context, state)
            domains = list(context.domain_options)
        return context, domains

    def _update_state_preview_metadata(
        self,
        state: InteractiveProviderState,
        *,
        timeline: Sequence[AliasProviderStage],
        capture_summary: Sequence[AliasProviderCapture],
    ) -> None:
        if timeline:
            last_stage = timeline[-1]
            state.current_stage = {"code": last_stage.code, "label": last_stage.label}
        else:
            state.current_stage = {"code": "", "label": ""}
        state.stage_history = [self._stage_to_state_item(item) for item in timeline]
        state.last_failure = {"stageCode": "", "stageLabel": "", "reason": ""}
        state.last_error = ""
        state.last_capture_summary = [self._capture_to_state_item(item) for item in capture_summary]

    def _add_new_alias_leases(
        self,
        pool_manager,
        *,
        state: InteractiveProviderState,
        known_aliases_before: Sequence[str],
    ) -> None:
        known_before_set = {str(item or "").strip().lower() for item in known_aliases_before if str(item or "").strip()}
        if state.accounts_state:
            for account in list(state.accounts_state or []):
                if not isinstance(account, Mapping):
                    continue
                real_mailbox_email = str(
                    account.get("real_mailbox_email") or account.get("service_account_email") or ""
                ).strip().lower()
                for email in self._account_known_aliases(account):
                    if email in known_before_set:
                        continue
                    known_before_set.add(email)
                    pool_manager.add_lease(
                        AliasEmailLease(
                            alias_email=email,
                            real_mailbox_email=real_mailbox_email,
                            source_kind=self.provider_type,
                            source_id=self.source_id,
                            source_session_id=self._spec.state_key or self.source_id,
                        )
                    )
            return

        real_mailbox_email = str(state.real_mailbox_email or "").strip().lower()
        for email in self._flatten_known_aliases(state):
            if email in known_before_set:
                continue
            known_before_set.add(email)
            pool_manager.add_lease(
                AliasEmailLease(
                    alias_email=email,
                    real_mailbox_email=real_mailbox_email,
                    source_kind=self.provider_type,
                    source_id=self.source_id,
                    source_session_id=self._spec.state_key or self.source_id,
                )
            )

    def _seed_context_from_state(
        self,
        context: AuthenticatedProviderContext,
        state: InteractiveProviderState,
    ) -> AuthenticatedProviderContext:
        account_state = self._active_account_state_item(state)
        if account_state is not None:
            domain_options = list(context.domain_options)
            if not domain_options:
                domain_options = self._domain_options_from_items(account_state.get("domain_options"))
            return replace(
                context,
                service_account_email=str(account_state.get("service_account_email") or context.service_account_email or ""),
                confirmation_inbox_email=str(
                    account_state.get("confirmation_inbox_email") or context.confirmation_inbox_email or ""
                ),
                real_mailbox_email=str(account_state.get("real_mailbox_email") or context.real_mailbox_email or ""),
                service_password=str(account_state.get("service_password") or context.service_password or ""),
                username=str(account_state.get("username") or context.username or ""),
                session_state=dict(account_state.get("session_state") or context.session_state or {}),
                domain_options=domain_options,
            )

        domain_options = list(context.domain_options)
        if not domain_options:
            domain_options = self._domain_options_from_state(state)

        return replace(
            context,
            service_account_email=str(state.service_account_email or context.service_account_email or ""),
            confirmation_inbox_email=str(state.confirmation_inbox_email or context.confirmation_inbox_email or ""),
            real_mailbox_email=str(state.real_mailbox_email or context.real_mailbox_email or ""),
            service_password=str(state.service_password or context.service_password or ""),
            username=str(state.username or context.username or ""),
            session_state=dict(state.session_state or context.session_state or {}),
            domain_options=domain_options,
        )

    def _dedupe_alias_items(self, aliases: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
        unique_aliases: list[dict[str, object]] = []
        seen: set[str] = set()
        for item in aliases:
            email = str(item.get("email") or "").strip().lower()
            if not email or email in seen:
                continue
            seen.add(email)
            normalized = dict(item)
            normalized["email"] = email
            unique_aliases.append(normalized)
        return unique_aliases

    def _dedupe_alias_values(self, aliases: Sequence[object]) -> list[str]:
        unique_aliases: list[str] = []
        seen: set[str] = set()
        for item in aliases:
            email = str(item or "").strip().lower()
            if not email or email in seen:
                continue
            seen.add(email)
            unique_aliases.append(email)
        return unique_aliases

    def _alias_values_from_items(self, aliases: Sequence[Mapping[str, object]]) -> list[str]:
        return self._dedupe_alias_values([item.get("email") for item in aliases])

    def _normalize_domain_state_items(self, items) -> list[dict[str, object]]:
        normalized: list[dict[str, object]] = []
        for item in list(items or []):
            if not isinstance(item, Mapping):
                continue
            normalized.append(
                {
                    "key": str(item.get("key") or ""),
                    "domain": str(item.get("domain") or ""),
                    "label": str(item.get("label") or ""),
                    "raw": dict(item.get("raw") or {}) if isinstance(item.get("raw"), Mapping) else {},
                }
            )
        return normalized

    def _domain_options_from_items(self, items) -> list[AliasDomainOption]:
        domains: list[AliasDomainOption] = []
        for item in self._normalize_domain_state_items(items):
            domains.append(
                AliasDomainOption(
                    key=str(item.get("key") or ""),
                    domain=str(item.get("domain") or ""),
                    label=str(item.get("label") or ""),
                    raw=dict(item.get("raw") or {}) if isinstance(item.get("raw"), Mapping) else {},
                )
            )
        return domains

    def _has_legacy_account_state(self, state: InteractiveProviderState) -> bool:
        return any(
            [
                str(state.service_account_email or "").strip(),
                str(state.confirmation_inbox_email or "").strip(),
                str(state.real_mailbox_email or "").strip(),
                str(state.service_password or "").strip(),
                str(state.username or "").strip(),
                bool(state.session_state),
                bool(state.domain_options),
                bool(state.known_aliases),
            ]
        )

    def _legacy_account_state_item(
        self,
        state: InteractiveProviderState,
        account: Mapping[str, object],
    ) -> dict[str, object]:
        return {
            "email": str(account.get("email") or "").strip().lower(),
            "password": str(account.get("password") or "").strip(),
            "label": str(account.get("label") or "").strip(),
            "service_account_email": str(state.service_account_email or account.get("email") or "").strip().lower(),
            "confirmation_inbox_email": str(state.confirmation_inbox_email or "").strip().lower(),
            "real_mailbox_email": str(state.real_mailbox_email or "").strip().lower(),
            "service_password": str(state.service_password or account.get("password") or "").strip(),
            "username": str(state.username or account.get("label") or "").strip(),
            "session_state": dict(state.session_state or {}),
            "domain_options": self._normalize_domain_state_items(state.domain_options),
            "known_aliases": self._dedupe_alias_values(list(state.known_aliases or [])),
            "exhausted": False,
        }

    def _find_account_state_item(
        self,
        state: InteractiveProviderState,
        account_email: str,
    ) -> dict[str, object] | None:
        normalized_email = str(account_email or "").strip().lower()
        if not normalized_email:
            return None
        for item in list(state.accounts_state or []):
            if not isinstance(item, dict):
                continue
            email = str(item.get("email") or "").strip().lower()
            if email == normalized_email:
                return item
        return None

    def _active_account_state_item(self, state: InteractiveProviderState) -> dict[str, object] | None:
        active_account = self._find_account_state_item(state, state.active_account_email)
        if active_account is not None:
            return active_account
        return self._find_account_state_item(state, state.service_account_email)

    def _set_active_account(self, state: InteractiveProviderState, account_email: str) -> None:
        normalized_email = str(account_email or "").strip().lower()
        if not normalized_email:
            state.active_account_email = ""
            return
        state.active_account_email = normalized_email
        active_account = self._find_account_state_item(state, normalized_email)
        if active_account is not None:
            self._sync_legacy_fields_from_account(state, active_account)

    def _sync_legacy_fields_from_account(
        self,
        state: InteractiveProviderState,
        account: Mapping[str, object],
    ) -> None:
        state.service_account_email = str(account.get("service_account_email") or account.get("email") or "").strip().lower()
        state.confirmation_inbox_email = str(account.get("confirmation_inbox_email") or "").strip().lower()
        state.real_mailbox_email = str(account.get("real_mailbox_email") or "").strip().lower()
        state.service_password = str(account.get("service_password") or account.get("password") or "").strip()
        state.username = str(account.get("username") or account.get("label") or "").strip()
        state.session_state = dict(account.get("session_state") or {})
        state.domain_options = self._normalize_domain_state_items(account.get("domain_options"))

    def _account_known_aliases(self, account: Mapping[str, object]) -> list[str]:
        return self._dedupe_alias_values(list(account.get("known_aliases") or []))

    def _account_is_full(self, known_aliases: Sequence[object]) -> bool:
        single_account_cap = self._single_account_alias_cap()
        return bool(single_account_cap and len(self._dedupe_alias_values(known_aliases)) >= single_account_cap)

    def _all_accounts_exhausted(self, state: InteractiveProviderState) -> bool:
        if not state.accounts_state:
            return False
        return all(
            bool(item.get("exhausted")) or self._account_is_full(self._account_known_aliases(item))
            for item in state.accounts_state
            if isinstance(item, Mapping)
        )

    def _update_state_from_context(self, state: InteractiveProviderState, context: AuthenticatedProviderContext) -> None:
        active_account = self._active_account_state_item(state)
        if active_account is not None:
            active_account["service_account_email"] = context.service_account_email
            active_account["confirmation_inbox_email"] = context.confirmation_inbox_email
            active_account["real_mailbox_email"] = context.real_mailbox_email
            active_account["service_password"] = context.service_password
            active_account["username"] = context.username
            active_account["session_state"] = dict(context.session_state)
        state.service_account_email = context.service_account_email
        state.confirmation_inbox_email = context.confirmation_inbox_email
        state.real_mailbox_email = context.real_mailbox_email
        state.service_password = context.service_password
        state.username = context.username
        state.session_state = dict(context.session_state)

    def _domain_options_from_state(self, state: InteractiveProviderState) -> list[AliasDomainOption]:
        return self._domain_options_from_items(state.domain_options)

    def _update_state_snapshot(
        self,
        state: InteractiveProviderState,
        *,
        context: AuthenticatedProviderContext,
        domains: Sequence[AliasDomainOption],
        aliases: Sequence[Mapping[str, object]],
        timeline: Sequence[AliasProviderStage],
        capture_summary: Sequence[AliasProviderCapture],
    ) -> None:
        self._update_state_from_context(state, context)
        domain_state_items = [self._domain_to_state_item(item) for item in domains]
        alias_values = [
            str(item.get("email") or "").strip().lower()
            for item in aliases
            if str(item.get("email") or "").strip()
        ]
        active_account = self._active_account_state_item(state)
        if active_account is not None:
            active_account["domain_options"] = domain_state_items
            active_account["known_aliases"] = self._dedupe_alias_values(alias_values)
            if self._account_is_full(active_account["known_aliases"]):
                active_account["exhausted"] = True
            self._sync_legacy_fields_from_account(state, active_account)
            state.known_aliases = self._flatten_known_aliases(state)
        else:
            state.domain_options = domain_state_items
            state.known_aliases = self._dedupe_alias_values(alias_values)
        if timeline:
            last_stage = timeline[-1]
            state.current_stage = {"code": last_stage.code, "label": last_stage.label}
        else:
            state.current_stage = {"code": "", "label": ""}
        state.stage_history = [self._stage_to_state_item(item) for item in timeline]
        state.last_failure = {"stageCode": "", "stageLabel": "", "reason": ""}
        state.last_error = ""
        state.last_capture_summary = [self._capture_to_state_item(item) for item in capture_summary]

    def _domain_to_state_item(self, domain: AliasDomainOption) -> dict[str, object]:
        return {
            "key": domain.key,
            "domain": domain.domain,
            "label": domain.label,
            "raw": dict(domain.raw),
        }

    def _stage_to_state_item(self, stage: AliasProviderStage) -> dict[str, str]:
        return {
            "code": stage.code,
            "label": stage.label,
            "status": stage.status,
            "detail": stage.detail,
        }

    def _capture_to_state_item(self, capture: AliasProviderCapture) -> dict[str, object]:
        return {
            "kind": capture.kind,
            "request_summary": dict(capture.request_summary),
            "response_summary": dict(capture.response_summary),
            "redaction_applied": bool(capture.redaction_applied),
        }

    def pick_domain_option(self, domains: list[AliasDomainOption], alias_index: int) -> AliasDomainOption | None:
        if not domains:
            return None
        return domains[(alias_index - 1) % len(domains)]

    def build_capture_summary(self) -> list[AliasProviderCapture]:
        return []

    def list_existing_aliases(self, context: AuthenticatedProviderContext) -> list[dict[str, str]]:
        return []

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        raise NotImplementedError

    def resolve_verification_requirements(self, context: AuthenticatedProviderContext) -> list[VerificationRequirement]:
        return []

    def satisfy_verification_requirement(
        self,
        requirement: VerificationRequirement,
        context: AuthenticatedProviderContext,
    ) -> AuthenticatedProviderContext:
        return context

    def discover_alias_domains(self, context: AuthenticatedProviderContext) -> list[AliasDomainOption]:
        return []

    def create_alias(
        self,
        *,
        context: AuthenticatedProviderContext,
        domain: AliasDomainOption | None,
        alias_index: int,
    ) -> AliasCreatedRecord:
        raise NotImplementedError


class ExistingAccountAliasProviderBase(InteractiveAliasProviderBase):
    def select_service_account(self) -> dict[str, str]:
        state = self._account_selection_state or self._state_repository.load()
        accounts = self._build_accounts_state(state)
        if not accounts:
            raise RuntimeError(f"{self.provider_type} provider requires at least one existing account")

        account = self._select_next_available_account(state)
        if account is None:
            raise RuntimeError(f"{self.provider_type} provider has no remaining available account")

        email = str(account.get("email") or "").strip().lower()
        password = str(account.get("password") or account.get("service_password") or email).strip() or email
        label = str(account.get("label") or account.get("username") or email.split("@")[0]).strip()
        return {"email": email, "password": password, "label": label or email}


class _PreviewPoolManager:
    def add_lease(self, lease: AliasEmailLease) -> None:
        return None
