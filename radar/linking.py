"""Link journal articles to the working papers we saw earlier."""
from __future__ import annotations

from radar.db import DB


def link_published(db: DB) -> int:
    n = 0
    rows = db.conn.execute("SELECT * FROM papers WHERE kind='pub' AND published_match IS NULL AND digested_on IS NULL").fetchall()
    for pub in rows:
        wps = db.working_papers_matching(pub["title"])
        if wps:
            wp = wps[0]
            db.set_fields(int(pub["seq"]), published_match=int(wp["seq"]))
            n += 1
    return n
