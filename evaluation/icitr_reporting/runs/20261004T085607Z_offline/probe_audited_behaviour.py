"""Run against the audited snapshot (29f926f) with a fake model; no network."""
import asyncio, json, os, sqlite3, sys
os.environ["OPENAI_API_KEY"] = "sk-x"
os.environ["COMMUNITY_REPORTS_DB"] = os.path.abspath("probe.db")
os.environ["REPORT_IMAGES_DIR"] = os.path.abspath("probe_images")
sys.path.insert(0, ".")
if os.path.exists("probe.db"):
    os.remove("probe.db")
from agent.reporter import CommunityReporter

class Fake:
    def __init__(self, replies): self.replies = list(replies)
    async def ainvoke(self, msgs):
        r = self.replies.pop(0)
        if isinstance(r, Exception): raise r
        return type("M", (), {"content": r})()

r = CommunityReporter()
async def no_rain(loc): return None
r._fetch_rainfall_for_location = no_rain

# (a) repeated verification of the same report
with sqlite3.connect(r.db_path) as c:
    c.execute("INSERT INTO user_reliability VALUES ('u1',0.5,1,0,0,'x')")
traj = []
for _ in range(3):
    r.update_user_reliability("u1", verified=True)   # what /verify calls on every request
    traj.append(r._get_user_reliability("u1"))
print("a) reliability after verifying the same report 3 times:", traj)

# (b) vision inference failure
r.llm = Fake([RuntimeError("upstream 500")])
a = asyncio.run(r._analyze_image_evidence(b"\xff\xd8\xff" + b"0" * 50, "image/jpeg", "flood", "en"))
print("b) evidence_score after vision failure:", a["evidence_score"])

# (c) storage failure
with sqlite3.connect(r.db_path) as c:
    c.execute("CREATE TRIGGER f BEFORE INSERT ON report_status_log BEGIN SELECT RAISE(ABORT,'simulated'); END")
text = json.dumps({"report_domain": "hazard", "hazard_type": "flood", "category": "flood", "location_text": "Kelaniya",
                   "location_specific": True, "description": "Water rising on the main road in Kelaniya.",
                   "people_at_risk": True, "ongoing": True, "hazard_scale": "moderate", "infrastructure_damage": False})
r.llm = Fake([text])
out = asyncio.run(r.process_report("94770000000", "Water rising in Kelaniya", "en"))
with sqlite3.connect(r.db_path) as c:
    n = c.execute("select count(*) from community_reports").fetchone()[0]
print("c) stored flag returned:", out["stored"], "| rows in community_reports:", n, "| reply starts:", out["response"][:26])
