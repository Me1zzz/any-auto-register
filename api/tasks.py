from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from typing import Any, Optional, cast
from copy import deepcopy
from core.db import TaskLog, engine
from core.task_runtime import (
    AttemptOutcome,
    AttemptResult,
    RegisterTaskStore,
    SkipCurrentAttemptRequested,
    StopTaskRequested,
)
import time, json, asyncio, threading, logging

router = APIRouter(prefix="/tasks", tags=["tasks"])
logger = logging.getLogger(__name__)

MAX_FINISHED_TASKS = 200
CLEANUP_THRESHOLD = 250
_task_store = RegisterTaskStore(
    max_finished_tasks=MAX_FINISHED_TASKS,
    cleanup_threshold=CLEANUP_THRESHOLD,
)


class RegisterTaskRequest(BaseModel):
    platform: str
    email: Optional[str] = None
    password: Optional[str] = None
    count: int = 1
    concurrency: int = 1
    register_delay_seconds: float = 0
    proxy: Optional[str] = None
    executor_type: str = "protocol"
    captcha_solver: str = "yescaptcha"
    extra: dict = Field(default_factory=dict)


class TaskLogBatchDeleteRequest(BaseModel):
    ids: list[int]


def _ensure_task_exists(task_id: str) -> None:
    if not _task_store.exists(task_id):
        raise HTTPException(404, "任务不存在")


def _ensure_task_mutable(task_id: str) -> None:
    _ensure_task_exists(task_id)
    snapshot = _task_store.snapshot(task_id)
    if snapshot.get("status") in {"done", "failed", "stopped"}:
        raise HTTPException(409, "任务已结束，无法再执行控制操作")


def _prepare_register_request(req: RegisterTaskRequest) -> RegisterTaskRequest:
    from core.config_store import config_store

    req_data = req.model_dump()
    req_data["extra"] = deepcopy(req_data.get("extra") or {})
    prepared = RegisterTaskRequest(**req_data)

    mail_provider = prepared.extra.get("mail_provider") or config_store.get(
        "mail_provider", ""
    )
    if mail_provider == "luckmail":
        platform = prepared.platform
        if platform in ("tavily", "openblocklabs"):
            raise HTTPException(400, f"LuckMail 渠道暂时不支持 {platform} 项目注册")

        mapping = {
            "trae": "trae",
            "cursor": "cursor",
            "grok": "grok",
            "kiro": "kiro",
            "chatgpt": "openai",
        }
        prepared.extra["luckmail_project_code"] = mapping.get(platform, platform)

    return prepared


def _create_task_record(
    task_id: str, req: RegisterTaskRequest, source: str, meta: dict | None = None
):
    _task_store.create(
        task_id,
        platform=req.platform,
        total=req.count,
        source=source,
        meta=meta,
    )


def enqueue_register_task(
    req: RegisterTaskRequest,
    *,
    background_tasks: BackgroundTasks | None = None,
    source: str = "manual",
    meta: dict | None = None,
) -> str:
    prepared = _prepare_register_request(req)
    task_id = f"task_{int(time.time() * 1000)}"
    _create_task_record(task_id, prepared, source, meta)
    if background_tasks is None:
        thread = threading.Thread(
            target=_run_register, args=(task_id, prepared), daemon=True
        )
        thread.start()
    else:
        background_tasks.add_task(_run_register, task_id, prepared)
    return task_id


def has_active_register_task(
    *, platform: str | None = None, source: str | None = None
) -> bool:
    return _task_store.has_active(platform=platform, source=source)


def _log(task_id: str, msg: str):
    """向任务追加一条日志"""
    ts = time.strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    _task_store.append_log(task_id, entry)
    print(entry)


def _save_task_log(
    platform: str, email: str, status: str, error: str = "", detail: dict | None = None
):
    """Write a TaskLog record to the database."""
    with Session(engine) as s:
        log = TaskLog(
            platform=platform,
            email=email,
            status=status,
            error=error,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
        s.add(log)
        s.commit()


def _auto_upload_integrations(task_id: str, account):
    """注册成功后自动导入外部系统。"""
    try:
        from services.external_sync import sync_account

        for result in sync_account(account):
            name = result.get("name", "Auto Upload")
            ok = bool(result.get("ok"))
            msg = result.get("msg", "")
            _log(task_id, f"  [{name}] {'[OK] ' + msg if ok else '[FAIL] ' + msg}")
    except Exception as e:
        _log(task_id, f"  [Auto Upload] 自动导入异常: {e}")


def _run_register(task_id: str, req: RegisterTaskRequest):
    from core.alias_pool.alias_email_provider import build_alias_email_alias_provider
    from core.registry import get
    from core.alias_pool.config import (
        build_alias_provider_source_specs,
        normalize_cloudmail_alias_pool_config,
    )
    from core.alias_pool.emailshield_provider import build_emailshield_alias_provider
    from core.alias_pool.lease_consumer import AliasLeaseConsumerContext
    from core.alias_pool.manager import AliasEmailPoolManager
    from core.alias_pool.myalias_pro_provider import build_myalias_pro_alias_provider
    from core.alias_pool.provider_adapters import (
        build_simple_generator_alias_provider,
        build_static_list_alias_provider,
    )
    from core.alias_pool.provider_bootstrap import AliasProviderBootstrap
    from core.alias_pool.provider_contracts import (
        AliasProvider,
        AliasProviderBootstrapContext,
        AliasProviderSourceSpec,
    )
    from core.alias_pool.provider_registry import AliasProviderRegistry
    from core.alias_pool.secureinseconds_provider import build_secureinseconds_alias_provider
    from core.alias_pool.simplelogin_provider import build_simplelogin_alias_provider
    from core.alias_pool.vend_email_service import build_vend_email_alias_service_producer
    from core.base_platform import RegisterConfig
    from core.db import save_account
    from core.base_mailbox import create_mailbox
    from core.proxy_utils import normalize_proxy_url

    control = _task_store.control_for(task_id)
    _task_store.mark_running(task_id)
    success = 0
    skipped = 0
    errors = []
    workspace_success = 0
    start_gate_lock = threading.Lock()
    workspace_progress_lock = threading.Lock()
    next_start_time = time.time()

    def _sleep_with_control(
        wait_seconds: float,
        *,
        attempt_id: int | None = None,
    ) -> None:
        remaining = max(float(wait_seconds or 0), 0.0)
        while remaining > 0:
            control.checkpoint(attempt_id=attempt_id)
            chunk = min(0.25, remaining)
            time.sleep(chunk)
            remaining -= chunk

    try:
        PlatformCls = get(req.platform)

        def _build_mailbox(proxy: Optional[str]):
            from core.config_store import config_store

            merged_extra = config_store.get_all().copy()
            merged_extra.update(
                {k: v for k, v in req.extra.items() if v is not None and v != ""}
            )
            return create_mailbox(
                provider=merged_extra.get("mail_provider", "luckmail"),
                extra=merged_extra,
                proxy=proxy or "",
            )

        def _build_alias_pool(merged_extra: dict):
            def _build_vend_email_provider(
                spec: AliasProviderSourceSpec,
                context: AliasProviderBootstrapContext,
            ) -> AliasProvider:
                return cast(
                    AliasProvider,
                    build_vend_email_alias_service_producer(
                        source=dict(spec.raw_source or {}),
                        task_id=context.task_id,
                        state_store_factory=context.state_store_factory,
                        runtime_builder=context.runtime_builder,
                    ),
                )

            pool_config = normalize_cloudmail_alias_pool_config(
                merged_extra,
                task_id=task_id,
            )
            if not pool_config.get("enabled"):
                return None

            manager = AliasEmailPoolManager(task_id=task_id)
            registry = AliasProviderRegistry()
            registry.register("static_list", build_static_list_alias_provider)
            registry.register("simple_generator", build_simple_generator_alias_provider)
            registry.register("vend_email", _build_vend_email_provider)
            registry.register("myalias_pro", build_myalias_pro_alias_provider)
            registry.register("secureinseconds", build_secureinseconds_alias_provider)
            registry.register("emailshield", build_emailshield_alias_provider)
            registry.register("simplelogin", build_simplelogin_alias_provider)
            registry.register("alias_email", build_alias_email_alias_provider)
            bootstrap = AliasProviderBootstrap(registry=registry)
            bootstrap_context = AliasProviderBootstrapContext(
                task_id=task_id,
                purpose="task_pool",
                runtime_builder=merged_extra.get("vend_email_runtime_builder"),
                state_store_factory=merged_extra.get("vend_email_state_store_factory"),
            )
            for spec in build_alias_provider_source_specs(pool_config):
                producer = bootstrap.build(spec=spec, context=bootstrap_context)
                manager.register_source(producer)
                producer.load_into(manager)
            return manager

        from core.config_store import config_store

        task_merged_extra = config_store.get_all().copy()
        task_merged_extra.update(
            {k: v for k, v in req.extra.items() if v is not None and v != ""}
        )
        task_alias_pool = _build_alias_pool(task_merged_extra)
        task_alias_consumer = (
            AliasLeaseConsumerContext(pool_manager=task_alias_pool)
            if task_alias_pool is not None
            else None
        )

        def _do_one(i: int):
            nonlocal next_start_time, workspace_success
            proxy_pool = None
            _proxy = None
            current_email = req.email or ""
            attempt_id: int | None = None
            try:
                from core.proxy_pool import proxy_pool

                control.checkpoint()
                attempt_id = control.start_attempt()
                control.checkpoint(attempt_id=attempt_id)
                _proxy = req.proxy
                if not _proxy:
                    _proxy = proxy_pool.get_next()
                _proxy = normalize_proxy_url(_proxy)
                if req.register_delay_seconds > 0:
                    with start_gate_lock:
                        control.checkpoint(attempt_id=attempt_id)
                        now = time.time()
                        wait_seconds = max(0.0, next_start_time - now)
                        if wait_seconds > 0:
                            _log(
                                task_id,
                                f"第 {i + 1} 个账号启动前延迟 {wait_seconds:g} 秒",
                            )
                            _sleep_with_control(
                                wait_seconds,
                                attempt_id=attempt_id,
                            )
                        next_start_time = time.time() + req.register_delay_seconds
                control.checkpoint(attempt_id=attempt_id)
                from core.config_store import config_store

                merged_extra = config_store.get_all().copy()
                merged_extra.update(
                    {k: v for k, v in req.extra.items() if v is not None and v != ""}
                )

                _config = RegisterConfig(
                    executor_type=req.executor_type,
                    captcha_solver=req.captcha_solver,
                    proxy=_proxy,
                    extra=merged_extra,
                )
                _mailbox = _build_mailbox(_proxy)
                if hasattr(_mailbox, "_task_alias_pool_key"):
                    setattr(_mailbox, "_task_alias_pool_key", task_id)
                if task_alias_consumer is not None:
                    _mailbox.bind_alias_consumer(task_alias_consumer)
                if hasattr(_mailbox, "_task_alias_pool"):
                    setattr(_mailbox, "_task_alias_pool", task_alias_pool)
                platform_ctor = cast(Any, PlatformCls)
                _platform = cast(Any, platform_ctor(config=_config, mailbox=_mailbox))
                _platform._task_attempt_token = attempt_id
                _platform._log_fn = lambda msg: _log(task_id, msg)
                _platform.bind_task_control(control)
                if getattr(_platform, "mailbox", None) is not None:
                    _platform.mailbox._task_attempt_token = attempt_id
                    _platform.mailbox._log_fn = _platform._log_fn
                _task_store.set_progress(task_id, f"{i + 1}/{req.count}")
                _log(task_id, f"开始注册第 {i + 1}/{req.count} 个账号")
                if _proxy:
                    _log(task_id, f"使用代理: {_proxy}")
                account = _platform.register(
                    email=req.email or "",
                    password=req.password or "",
                )
                current_email = account.email or current_email
                if isinstance(account.extra, dict):
                    mailbox_account = getattr(_mailbox, "_last_account", None)
                    mailbox_extra = getattr(mailbox_account, "extra", None)
                    if isinstance(mailbox_extra, dict):
                        for extra_key, extra_value in mailbox_extra.items():
                            account.extra.setdefault(extra_key, extra_value)
                    mailbox_account_id = str(getattr(mailbox_account, "account_id", "") or "").strip()
                    if mailbox_account_id and mailbox_account_id != account.email:
                        account.extra.setdefault("mailbox_email", mailbox_account_id)
                    mail_provider = merged_extra.get("mail_provider", "")
                    if mail_provider:
                        account.extra.setdefault("mail_provider", mail_provider)
                    if mail_provider == "luckmail" and req.platform == "chatgpt":
                        mailbox_token = getattr(_mailbox, "_token", "") or ""
                        if mailbox_token:
                            account.extra.setdefault("mailbox_token", mailbox_token)
                        if merged_extra.get("luckmail_project_code"):
                            account.extra.setdefault(
                                "luckmail_project_code",
                                merged_extra.get("luckmail_project_code"),
                            )
                        if merged_extra.get("luckmail_email_type"):
                            account.extra.setdefault(
                                "luckmail_email_type",
                                merged_extra.get("luckmail_email_type"),
                            )
                        if merged_extra.get("luckmail_domain"):
                            account.extra.setdefault(
                                "luckmail_domain", merged_extra.get("luckmail_domain")
                            )
                        if merged_extra.get("luckmail_base_url"):
                            account.extra.setdefault(
                                "luckmail_base_url",
                                merged_extra.get("luckmail_base_url"),
                            )
                saved_account = save_account(account)
                if _proxy:
                    proxy_pool.report_success(_proxy)
                _log(task_id, f"[OK] 注册成功: {account.email}")
                workspace_id = ""
                if isinstance(account.extra, dict):
                    workspace_id = str(account.extra.get("workspace_id") or "").strip()
                if workspace_id:
                    with workspace_progress_lock:
                        workspace_success += 1
                        _log(task_id, f"[ChatGPT] workspace进度: {workspace_success}/{req.count}")
                _save_task_log(req.platform, account.email, "success")
                _auto_upload_integrations(task_id, saved_account or account)
                cashier_url = (account.extra or {}).get("cashier_url", "")
                if cashier_url:
                    _log(task_id, f"  [升级链接] {cashier_url}")
                    _task_store.add_cashier_url(task_id, cashier_url)
                return AttemptResult.success()
            except SkipCurrentAttemptRequested as e:
                _log(task_id, f"[SKIP] 已跳过当前账号: {e}")
                _save_task_log(
                    req.platform,
                    current_email,
                    "skipped",
                    error=str(e),
                )
                return AttemptResult.skipped(str(e))
            except StopTaskRequested as e:
                _log(task_id, f"[STOP] {e}")
                return AttemptResult.stopped(str(e))
            except Exception as e:
                if _proxy and proxy_pool is not None:
                    proxy_pool.report_fail(_proxy)
                _log(task_id, f"[FAIL] 注册失败: {e}")
                _save_task_log(
                    req.platform,
                    current_email,
                    "failed",
                    error=str(e),
                )
                return AttemptResult.failed(str(e))
            finally:
                control.finish_attempt(attempt_id)

        from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed

        max_workers = min(req.concurrency, req.count, 5)
        stopped = False
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_do_one, i) for i in range(req.count)]
            for f in as_completed(futures):
                try:
                    result = f.result()
                except CancelledError:
                    continue
                except Exception as e:
                    _log(task_id, f"[ERROR] 任务线程异常: {e}")
                    errors.append(str(e))
                    continue
                if result.outcome == AttemptOutcome.SUCCESS:
                    success += 1
                elif result.outcome == AttemptOutcome.SKIPPED:
                    skipped += 1
                elif result.outcome == AttemptOutcome.STOPPED:
                    stopped = True
                else:
                    errors.append(result.message)
                if stopped or control.is_stop_requested():
                    stopped = True
                    for pending in futures:
                        if pending is not f:
                            pending.cancel()
    except Exception as e:
        _log(task_id, f"致命错误: {e}")
        _task_store.finish(
            task_id,
            status="failed",
            success=success,
            skipped=skipped,
            errors=errors,
            error=str(e),
        )
        _task_store.cleanup()
        return

    final_status = "stopped" if control.is_stop_requested() or stopped else "done"
    if final_status == "stopped":
        summary = (
            f"任务已停止: 成功 {success} 个, 跳过 {skipped} 个, 失败 {len(errors)} 个"
        )
    else:
        summary = f"完成: 成功 {success} 个, 跳过 {skipped} 个, 失败 {len(errors)} 个"
    _log(task_id, summary)
    try:
        from core.base_mailbox import CloudMailMailbox

        CloudMailMailbox.release_alias_pool(task_id)
    except Exception:
        pass
    if task_alias_consumer is not None:
        try:
            task_alias_consumer.release()
        except Exception:
            pass
    _task_store.finish(
        task_id,
        status=final_status,
        success=success,
        skipped=skipped,
        errors=errors,
    )
    _task_store.cleanup()


@router.post("/register")
def create_register_task(
    req: RegisterTaskRequest,
    background_tasks: BackgroundTasks,
):
    task_id = enqueue_register_task(req, background_tasks=background_tasks)
    return {"task_id": task_id}


@router.post("/{task_id}/skip-current")
def skip_current_account(task_id: str):
    _ensure_task_mutable(task_id)
    control = _task_store.request_skip_current(task_id)
    _log(task_id, "收到手动跳过当前账号请求")
    return {"ok": True, "task_id": task_id, "control": control}


@router.post("/{task_id}/stop")
def stop_task(task_id: str):
    _ensure_task_mutable(task_id)
    control = _task_store.request_stop(task_id)
    _log(task_id, "收到手动停止任务请求")
    return {"ok": True, "task_id": task_id, "control": control}


@router.get("/logs")
def get_logs(platform: str | None = None, page: int = 1, page_size: int = 50):
    with Session(engine) as s:
        q = select(TaskLog)
        if platform:
            q = q.where(TaskLog.platform == platform)
        q = q.order_by(cast(Any, TaskLog.id).desc())
        total = len(s.exec(q).all())
        items = s.exec(q.offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "items": items}


@router.post("/logs/batch-delete")
def batch_delete_logs(body: TaskLogBatchDeleteRequest):
    if not body.ids:
        raise HTTPException(400, "任务历史 ID 列表不能为空")

    unique_ids = list(dict.fromkeys(body.ids))
    if len(unique_ids) > 1000:
        raise HTTPException(400, "单次最多删除 1000 条任务历史")

    with Session(engine) as s:
        try:
            logs = s.exec(select(TaskLog).where(cast(Any, TaskLog.id).in_(unique_ids))).all()
            found_ids = {log.id for log in logs if log.id is not None}

            for log in logs:
                s.delete(log)

            s.commit()
            deleted_count = len(found_ids)
            not_found_ids = [log_id for log_id in unique_ids if log_id not in found_ids]
            logger.info("批量删除任务历史成功: %s 条", deleted_count)

            return {
                "deleted": deleted_count,
                "not_found": not_found_ids,
                "total_requested": len(unique_ids),
            }
        except Exception as e:
            s.rollback()
            logger.exception("批量删除任务历史失败")
            raise HTTPException(500, f"批量删除任务历史失败: {str(e)}")


@router.get("/{task_id}/logs/stream")
async def stream_logs(task_id: str, since: int = 0):
    """SSE 实时日志流"""
    _ensure_task_exists(task_id)

    async def event_generator():
        sent = since
        while True:
            logs, status = _task_store.log_state(task_id)
            while sent < len(logs):
                yield f"data: {json.dumps({'line': logs[sent]})}\n\n"
                sent += 1
            if status in ("done", "failed", "stopped"):
                yield f"data: {json.dumps({'done': True, 'status': status})}\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{task_id}")
def get_task(task_id: str):
    _ensure_task_exists(task_id)
    return _task_store.snapshot(task_id)


@router.get("")
def list_tasks():
    return _task_store.list_snapshots()
