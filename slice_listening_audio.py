#!/usr/bin/env python3
"""
聽力音檔逐題剪接 + 題庫指向更新

用法：
    python3 slice_listening_audio.py <時間表.csv>

時間表 CSV 欄位：音檔, 題目ID, 大題, 題號, 開始時間, 結束時間(可空)
- 開始時間格式：m:ss / mm:ss / h:mm:ss / 秒數（例：2:30、02:30、150）
- 結束時間留空 = 下一題的開始時間；同檔最後一題留空 = 檔尾

做咩：
1. 用 ffmpeg 將 13 個音檔逐題剪成 audio/sliced/<原檔>_q<NN>.mp3（128k 重編碼）
2. 寫 audio/sliced/audio_map.json（題目ID -> 新檔名）
3. 更新題庫 audio 欄位（先備份 .bak）：
   - your_files/jlpt-samples/ 3 個 listening bank
   - jlpt-deploy/question_bank.json
   - your_files/jlpt-daily-site/question_bank.json
4. 部署時 deploy_full.py 會自動上傳 audio/sliced/*.mp3

注意：題庫 patch 只認 題目ID；CSV 有題目ID 對唔上題庫會報錯停低。
"""
import csv, json, os, re, shutil, subprocess, sys

HOME = os.path.expanduser("~")
AUDIO_DIR = os.path.join(HOME, "workspace/jlpt-deploy/audio")
OUT_DIR = os.path.join(AUDIO_DIR, "sliced")
BANKS = [
    os.path.join(HOME, "workspace/your_files/jlpt-samples/n3_bank_2018_reading_listening.json"),
    os.path.join(HOME, "workspace/your_files/jlpt-samples/n4_bank_2018_listening.json"),
    os.path.join(HOME, "workspace/your_files/jlpt-samples/n5_bank_2018_reading_listening.json"),
    os.path.join(HOME, "workspace/jlpt-deploy/question_bank.json"),
    os.path.join(HOME, "workspace/your_files/jlpt-daily-site/question_bank.json"),
]
# 測試用：SLICE_TEST_BANKS=/tmp/a.json:/tmp/b.json
if os.environ.get("SLICE_TEST_BANKS"):
    BANKS = os.environ["SLICE_TEST_BANKS"].split(":")


def parse_time(s):
    s = (s or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    parts = s.split(":")
    try:
        parts = [float(p) for p in parts]
    except ValueError:
        raise ValueError(f"時間格式唔啱：{s}（用 m:ss 或秒數）")
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def fmt(sec):
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def ffprobe_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    csv_path = sys.argv[1]
    if len(sys.argv) > 2:
        global AUDIO_DIR, OUT_DIR
        AUDIO_DIR, OUT_DIR = sys.argv[2], sys.argv[3]

    # 讀時間表：按音檔分組，保持 CSV 內順序
    groups = {}
    order = []
    with open(csv_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            af, qid = (row.get("音檔") or "").strip(), (row.get("題目ID") or "").strip()
            st = parse_time(row.get("開始時間"))
            en = parse_time(row.get("結束時間(可空)"))
            if not af or not qid:
                continue
            if st is None:
                print(f"SKIP（未填開始時間）：{af} {qid}")
                continue
            if af not in groups:
                groups[af] = []
                order.append(af)
            groups[af].append({"qid": qid, "start": st, "end": en})

    if not groups:
        print("時間表冇有效行，停。")
        sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)
    audio_map = {}
    clip_count = 0

    for af in order:
        src = os.path.join(AUDIO_DIR, af)
        if not os.path.exists(src):
            print(f"ERROR：搵唔到音檔 {src}，停。")
            sys.exit(1)
        dur = ffprobe_duration(src)
        base = os.path.splitext(af)[0]
        qs = groups[af]
        for i, q in enumerate(qs):
            start = q["start"]
            end = q["end"] or (qs[i + 1]["start"] if i + 1 < len(qs) else dur)
            if end <= start:
                print(f"ERROR：{af} {q['qid']} 結束時間({fmt(end)}) <= 開始({fmt(start)})，停。")
                sys.exit(1)
            if start >= dur:
                print(f"ERROR：{af} {q['qid']} 開始時間超出音檔長度({fmt(dur)})，停。")
                sys.exit(1)
            end = min(end, dur)
            out_name = f"{base}_q{i+1:02d}.mp3"
            out_path = os.path.join(OUT_DIR, out_name)
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", str(start), "-to", str(end),
                 "-i", src, "-c:a", "libmp3lame", "-b:a", "128k", out_path],
                check=True)
            audio_map[q["qid"]] = f"sliced/{out_name}"
            clip_count += 1
            print(f"  {af} [{fmt(start)}-{fmt(end)}] -> {out_name}  ({q['qid']})")

    with open(os.path.join(OUT_DIR, "audio_map.json"), "w", encoding="utf-8") as f:
        json.dump(audio_map, f, ensure_ascii=False, indent=1)
    print(f"\n剪好 {clip_count} 段，map：{OUT_DIR}/audio_map.json")

    # 更新題庫
    total_patched = 0
    for bp in BANKS:
        if not os.path.exists(bp):
            print(f"WARN：題庫唔存在，跳過：{bp}")
            continue
        with open(bp, encoding="utf-8") as f:
            data = json.load(f)
        items = data["questions"] if isinstance(data, dict) and "questions" in data else data
        if not isinstance(items, list):
            print(f"WARN：題庫結構唔識，跳過：{bp}")
            continue
        patched = 0
        missing = []
        for it in items:
            if isinstance(it, dict) and it.get("id") in audio_map:
                it["audio"] = audio_map[it["id"]]
                patched += 1
        for qid in audio_map:
            if not any(isinstance(it, dict) and it.get("id") == qid for it in items):
                missing.append(qid)
        if patched:
            bak = bp + ".bak-slice"
            if not os.path.exists(bak):
                shutil.copy2(bp, bak)
            with open(bp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            print(f"  已更新 {bp}：{patched} 題（備份 {bak}）")
            total_patched += patched
        if missing:
            print(f"  WARN：{bp} 搵唔到呢啲題目ID：{missing[:5]}{'...' if len(missing)>5 else ''}")

    print(f"\n完成：{clip_count} 段音檔，題庫共更新 {total_patched} 處。")
    print("下一步：跑 deploy_full.py（會自動上傳 audio/sliced/*.mp3）。")


if __name__ == "__main__":
    main()
