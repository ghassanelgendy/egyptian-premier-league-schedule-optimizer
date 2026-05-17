from __future__ import annotations

import unittest
from unittest.mock import patch

import main
from src.baseline_retry import solve_baseline_with_domain_fallbacks


class PipelineDomainRetryTests(unittest.TestCase):
    def test_pipeline_retries_with_looser_epl_domain_policy(self) -> None:
        data = object()
        matches = [object()]
        baseline = [object()]

        with patch("src.fixture_generator.generate_drr", return_value=matches), patch(
            "src.slot_domain.build_domains",
            side_effect=[
                {0: [1, 2]},
                {0: [3, 4]},
            ],
        ) as build_domains_mock, patch(
            "src.baseline_solver.solve_baseline",
            side_effect=[None, baseline],
        ) as solve_mock, patch(
            "src.baseline_retry._annotate_baseline_status"
        ), patch(
            "src.output_writer.write_pre_caf_schedule"
        ), patch(
            "src.output_writer.write_final_schedule"
        ), patch(
            "src.output_writer.write_postponement_queue"
        ), patch(
            "src.output_writer.write_rescheduled_matches"
        ), patch(
            "src.output_writer.write_unresolved"
        ), patch(
            "src.output_writer.write_week_round_map"
        ), patch(
            "src.caf_audit.caf_audit",
            return_value=(baseline, []),
        ), patch(
            "src.caf_repair_solver.write_repair_skipped_status"
        ), patch(
            "src.validation.write_validation_reports",
            return_value=([], []),
        ):
            result = main.run_pipeline(data, seed=90, is_batch=False)

        self.assertTrue(result)
        self.assertEqual(build_domains_mock.call_count, 2)
        self.assertEqual(solve_mock.call_count, 2)
        self.assertEqual(
            [
                call.kwargs["non_final_policy"]
                for call in build_domains_mock.call_args_list
            ],
            ["compact", "epl_relaxed"],
        )

    def test_reuse_initial_compact_domains_before_fallback_rebuilds(self) -> None:
        data = object()
        matches = [object()]
        initial_domains = {0: [1, 2]}
        baseline = [object()]

        with patch(
            "src.slot_domain.build_domains",
            return_value={0: [3, 4]},
        ) as build_domains_mock, patch(
            "src.baseline_solver.solve_baseline",
            side_effect=[None, baseline],
        ) as solve_mock, patch(
            "src.baseline_retry._annotate_baseline_status"
        ):
            result, domain_policy = solve_baseline_with_domain_fallbacks(
                data,
                matches,
                is_batch=True,
                initial_domains=initial_domains,
                initial_policy="compact",
            )

        self.assertIs(result, baseline)
        self.assertEqual(domain_policy, "epl_relaxed")
        self.assertEqual(solve_mock.call_count, 2)
        self.assertEqual(build_domains_mock.call_count, 1)
        self.assertEqual(
            build_domains_mock.call_args.kwargs["non_final_policy"],
            "epl_relaxed",
        )


if __name__ == "__main__":
    unittest.main()
