import unittest

from core.alias_pool.automation_test import classify_probe_result_level


class RealFlowClassificationTests(unittest.TestCase):
    def test_classifies_placeholder_success_as_contract_ok(self):
        level = classify_probe_result_level(
            source_type="myalias_pro",
            ok=True,
            alias_email="myalias-1@myalias.pro",
            failure_stage_code="",
            runtime_evidence={},
        )
        self.assertEqual(level, "contract_ok")

    def test_classifies_signed_option_failure_as_real_flow_partial(self):
        level = classify_probe_result_level(
            source_type="simplelogin",
            ok=False,
            alias_email="",
            failure_stage_code="discover_alias_domains",
            runtime_evidence={"live_flow": True},
        )
        self.assertEqual(level, "real_flow_partial")

    def test_does_not_classify_heuristic_alias_shape_as_real_flow_complete_without_runtime_evidence(self):
        level = classify_probe_result_level(
            source_type="simplelogin",
            ok=True,
            alias_email="sisyrun0419a.relearn763@aleeas.com",
            failure_stage_code="",
            runtime_evidence={},
        )
        self.assertEqual(level, "contract_ok")

    def test_classifies_real_alias_as_real_flow_complete_with_runtime_evidence(self):
        level = classify_probe_result_level(
            source_type="simplelogin",
            ok=True,
            alias_email="sisyrun0419a.relearn763@aleeas.com",
            failure_stage_code="",
            runtime_evidence={"live_flow": True, "live_alias_creation": True, "confirmed_alias_creation": True},
        )
        self.assertEqual(level, "real_flow_complete")

    def test_classifies_real_simplelogin_alias_with_signed_suffix_as_real_flow_complete(self):
        level = classify_probe_result_level(
            source_type="simplelogin",
            ok=True,
            alias_email="real-1@aleeas.com.aexdfg.qpzcdintgotyfbybtzw6x9unyzy",
            failure_stage_code="",
            runtime_evidence={"live_flow": True, "live_alias_creation": True, "confirmed_alias_creation": True},
        )
        self.assertEqual(level, "real_flow_complete")

    def test_simplelogin_success_without_confirmed_creation_evidence_stays_partial(self):
        level = classify_probe_result_level(
            source_type="simplelogin",
            ok=True,
            alias_email="real-1@aleeas.com",
            failure_stage_code="",
            runtime_evidence={"live_flow": True, "live_alias_creation": True, "confirmed_alias_creation": False},
        )
        self.assertEqual(level, "real_flow_partial")

    def test_simplelogin_failed_after_live_flow_stays_partial(self):
        level = classify_probe_result_level(
            source_type="simplelogin",
            ok=False,
            alias_email="",
            failure_stage_code="create_aliases",
            runtime_evidence={"live_flow": True, "live_alias_creation": True, "confirmed_alias_creation": False},
        )
        self.assertEqual(level, "real_flow_partial")
