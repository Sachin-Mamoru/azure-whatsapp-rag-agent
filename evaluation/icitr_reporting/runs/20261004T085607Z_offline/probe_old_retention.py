import os, sqlite3, time, sys
from datetime import datetime, timedelta, timezone
os.environ["OPENAI_API_KEY"]="sk-x"; os.environ["COMMUNITY_REPORTS_DB"]=os.path.abspath("old.db")
sys.path.insert(0,".")
from agent.reporter import CommunityReporter
from agent import scheduler
r=CommunityReporter()
old=(datetime.now(timezone.utc)-timedelta(days=8)).isoformat()
with sqlite3.connect(r.db_path) as c:
    c.execute("INSERT INTO community_reports (report_id,timestamp,user_hash,language,report_domain,confidence_score,severity_score,action,status,created_at) VALUES ('R1',?,'u1','en','hazard',0.5,0.5,'monitor','new',?)",(old,old))
    c.execute("INSERT INTO user_reliability VALUES ('u1',0.5,1,0,0,?)",(old,))
scheduler._reporter_instance=r
t=time.time(); scheduler._retention_job(); print("elapsed_s", round(time.time()-t,2))
with sqlite3.connect(r.db_path) as c:
    print("status", c.execute("select status from community_reports").fetchall(), "reliability", c.execute("select reliability,n_rejected from user_reliability").fetchall())
