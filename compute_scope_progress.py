#!/usr/bin/env python3
"""預計「考試範圍完成度」四個百分比，寫成 scope-progress.json 推上網站。
用戶 2026-11-13 指示：數字唔使即時，每日 12:00／00:00 預計好，頁面只下載細 JSON。
計法同 index.html 舊版 updateScopeCard 完全一致：
  文法／讀解／聽解 = 後端 daily20_answer + mock_answer，每題取最新一次作答，對 QBANK 計正確率
  語彙 = 本人生字庫已收集字數 / 750
QBANK 合併次序同 loadQBank 一致（先出現者優先）。"""
import json, math, subprocess, sys, os, datetime

DEPLOY = os.path.expanduser('~/workspace/jlpt-deploy')
BASE = 'https://jlpt-scores.hoo-c27.workers.dev'
USERS = ['許悅', '許逸', 'GOBI']
QBANK_FILES = ['question_bank.json', 'question_bank_nihonez.json',
               'question_bank_nihonez_2025.json', 'question_bank_nihonez_n5_2025.json',
               'question_bank_nihonez_n5_2024.json', 'question_bank_nihonez_n3_2025.json',
               'question_bank_nihonez_wb2012.json']

def js_round(x):
    return math.floor(x + 0.5)

def fetch_json(args, timeout=180):
    out = subprocess.run(['curl', '-s', '--max-time', str(timeout)] + args,
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError('curl failed rc=%s %s' % (out.returncode, out.stderr[:200]))
    return json.loads(out.stdout)

def scores(t, who):
    return fetch_json(['-G', '--data-urlencode', 'type=' + t,
                       '--data-urlencode', 'who=' + who, BASE + '/scores'])

def load_qbank():
    ans, sec = {}, {}
    for fn in QBANK_FILES:
        with open(os.path.join(DEPLOY, fn), encoding='utf8') as f:
            j = json.load(f)
        qs = j.get('questions') if isinstance(j, dict) else j
        for q in qs or []:
            qid = q.get('id')
            if qid is None or qid in ans:
                continue
            ans[qid] = q.get('answer')
            sec[qid] = q.get('section')
    return ans, sec

def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

def compute(who, ans, sec, vocab):
    latest = {}
    for t in ('daily20_answer', 'mock_answer'):
        for r in scores(t, who) or []:
            k = r.get('key')
            if not k or k not in ans:
                continue
            cur = latest.get(k)
            if cur is None or (r.get('submittedAt') or 0) >= (cur.get('submittedAt') or 0):
                latest[k] = r
    st = {'grammar': [0, 0], 'reading': [0, 0], 'listening': [0, 0]}
    for k, r in latest.items():
        s = sec.get(k)
        if s not in st:
            continue
        st[s][1] += 1
        a1, a2 = num(r.get('answer')), num(ans[k])
        if a1 is not None and a1 == a2:
            st[s][0] += 1
    words = {it.get('word') for it in vocab if it.get('who') == who and it.get('word')}
    result = {'vocab': min(100, js_round(len(words) / 750 * 100))}
    for s in ('grammar', 'reading', 'listening'):
        c, n = st[s]
        result[s] = js_round(c / n * 100) if n > 0 else 0
    return result

def main():
    ans, sec = load_qbank()
    vocab = fetch_json([BASE + '/vocab']) or []
    users = {}
    for who in USERS:
        users[who] = compute(who, ans, sec, vocab)
        print(who, users[who], flush=True)
    payload = {'updated': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
               'users': users}
    path = os.path.join(DEPLOY, 'scope-progress.json')
    with open(path, 'w', encoding='utf8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print('wrote', path)
    p = subprocess.run(['python3', os.path.expanduser(
        '~/workspace/custom-connectors/custom.github/bin/gh-push.py')],
        cwd=DEPLOY, capture_output=True, text=True)
    print(p.stdout[-600:])
    if p.returncode != 0:
        print('PUSH FAILED', p.stderr[-400:])
        sys.exit(1)
    print('DONE')

if __name__ == '__main__':
    main()
