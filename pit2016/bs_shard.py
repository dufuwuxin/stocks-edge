# baostock 并行回补: 3 进程分片
import baostock as bs
import pandas as pd
import duckdb, os, time, sys

SHARD = int(sys.argv[1]); NSHARD = int(sys.argv[2])
OUT = "/home/agentuser/stockdb/t1/bs_qfq"
DONE = "/home/agentuser/stockdb/t1/_done_bs.txt"

done = set()
if os.path.exists(DONE):
    done = set(open(DONE).read().split())

con = duckdb.connect("/home/agentuser/stockdb/t1/qfq_all.duckdb", read_only=True)
syms = set(r[0] for r in con.execute("select distinct sym from qfq").fetchall())
con2 = duckdb.connect()
syms |= set(r[0] for r in con2.execute("select distinct symbol from read_parquet('/home/agentuser/stockdb/wh/daily/*.parquet') where symbol like 'sh6%' or symbol like 'sz0%' or symbol like 'sz3%'").fetchall())
codes = sorted(s for s in syms if s.startswith(("sh6","sz0","sz3")))
todo = [s for s in codes if s not in done and (hash(s) % NSHARD) == SHARD]
print(f"shard {SHARD}/{NSHARD}: {len(todo)}", flush=True)

lg = bs.login()
FIELDS = "date,code,open,high,low,close,volume,amount,turn,tradestatus,pctChg,isST"
for i, sym in enumerate(todo):
    code = sym[:2] + "." + sym[2:]
    try:
        rs = bs.query_history_k_data_plus(code, FIELDS, start_date='1990-01-01', end_date='2020-12-31',
            frequency="d", adjustflag="2")
        rows = []
        while rs.error_code == '0' and rs.next():
            rows.append(rs.get_row_data())
        if rows:
            pd.DataFrame(rows, columns=FIELDS.split(",")).to_parquet(f"{OUT}/{sym}.parquet", index=False)
        with open(DONE, "a") as f:
            f.write(sym + "\n")
        if i % 25 == 0:
            print(f"[{SHARD}] {i}/{len(todo)} {sym} rows={len(rows)}", flush=True)
    except Exception as e:
        print(f"[{SHARD}] ERR {sym}: {str(e)[:60]}", flush=True)
        time.sleep(1)
bs.logout()
print(f"[{SHARD}] DONE")
