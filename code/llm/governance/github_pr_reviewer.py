"""AIOS Autonomous GitHub PR Reviewer & Code Governance Bot.
Audits Git commits, Pull Requests, and code diffs using the 4-tier Multi-Agent Debate Tribunal,
producing structured security, performance, and architecture reviews.
"""
import os, sys, time, json, subprocess
from typing import Dict, Any, Optional
from pathlib import Path

sys.path.insert(0, '/opt')
sys.path.insert(0, '/opt/aios')

try:
    from aios.consensus.multi_agent_debate import MultiAgentDebateEngine
    debate_engine = MultiAgentDebateEngine.get_instance()
except Exception:
    debate_engine = None

AIOS_DIR = Path('/opt/aios')

class GitHubPRReviewer:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def review_latest_commit(self) -> Dict[str, Any]:
        """Reviews the most recent git commit in /opt/aios."""
        t0 = time.time()
        try:
            diff_res = subprocess.run(["git", "show", "HEAD", "--stat", "-p"], cwd=AIOS_DIR, capture_output=True, text=True, timeout=10)
            diff_text = diff_res.stdout[:3000] if diff_res.returncode == 0 else "No diff available"
            
            commit_info = subprocess.run(["git", "log", "-1", "--pretty=format:%h - %an: %s (%ci)"], cwd=AIOS_DIR, capture_output=True, text=True, timeout=5).stdout.strip()
            
            topic = f"Код-ревью коммита '{commit_info}'.\nДифф изменений:\n```diff\n{diff_text}\n```"
            
            if debate_engine:
                debate_res = debate_engine.conduct_debate_sync(topic)
                return {
                    "ok": True,
                    "commit": commit_info,
                    "review_latency_ms": round((time.time() - t0)*1000, 1),
                    "verdict": debate_res.get("consensus_verdict", ""),
                    "participants": debate_res.get("participants", {})
                }
            else:
                return {"ok": False, "error": "Debate engine not loaded"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def review_diff(self, diff_content: str, title: str = "Proposed PR Changes") -> Dict[str, Any]:
        """Reviews arbitrary git diff content."""
        if not debate_engine:
            return {"ok": False, "error": "Debate engine not loaded"}
            
        topic = f"Аудит Pull Request: '{title}'.\nДифф:\n```diff\n{diff_content[:3000]}\n```"
        res = debate_engine.conduct_debate_sync(topic)
        return {
            "ok": True,
            "title": title,
            "verdict": res.get("consensus_verdict", ""),
            "participants": res.get("participants", {})
        }

github_reviewer = GitHubPRReviewer.get_instance()

if __name__ == "__main__":
    print("🤖 Running Autonomous GitHub PR & Commit Reviewer...")
    rev = github_reviewer.review_latest_commit()
    print("Review Status:", rev.get("ok"))
    print(f"Commit: {rev.get('commit')}")
    print("\n🏛️ Итоговый вердикт ревьюера:")
    print(rev.get("verdict"))
