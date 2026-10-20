#!/usr/bin/env python3
"""穩陣讀取 jlpt-scores Worker"""
import urllib.request
import json
import time
import http.client

def fetch_scores(score_type, max_retries=5):
    """讀取指定類型，得唔到就重試"""
    url = f'https://jlpt-scores.hoo-c27.workers.dev/scores?type={score_type}'
    
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0',
                'Accept-Encoding': 'identity',
                'Connection': 'close',
            })
            # 用 http.client 直接控制
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
                # 處理可能嘅截斷
                if not raw:
                    raise ValueError("空回應")
                return json.loads(raw)
        except (http.client.IncompleteRead, ConnectionResetError) as e:
            # IncompleteRead：試下用已讀到嘅部分
            if hasattr(e, 'partial') and e.partial:
                try:
                    return json.loads(e.partial)
                except:
                    pass
            if attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            raise
    
    return []

if __name__ == '__main__':
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else 'qa_result'
    try:
        data = fetch_scores(t)
        print(f"{t}: {len(data)} 筆")
    except Exception as e:
        print(f"失敗: {type(e).__name__}: {e}")
