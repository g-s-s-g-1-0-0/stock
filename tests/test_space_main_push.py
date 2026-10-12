from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.space_main_push as space_main_push


ROOT_DIR = Path(__file__).resolve().parents[1]


class SpaceMainPushTest(unittest.TestCase):
    def test_waits_until_the_previous_main_commit_is_three_minutes_old(self) -> None:
        self.assertEqual(space_main_push.seconds_until_clear(1_000, 1_010), 170)
        self.assertEqual(space_main_push.seconds_until_clear(1_000, 1_180), 0)
        self.assertEqual(space_main_push.seconds_until_clear(1_000, 1_500), 0)

    def test_research_workflows_publish_away_from_main(self) -> None:
        for name in ("gap-go-observation.yml", "swing-data-first-observation.yml"):
            workflow = (ROOT_DIR / ".github" / "workflows" / name).read_text(encoding="utf-8")
            self.assertIn("bash scripts/publish_live_data.sh", workflow)
            self.assertNotIn('git push origin "HEAD:$BRANCH"', workflow)


if __name__ == "__main__":
    unittest.main()
