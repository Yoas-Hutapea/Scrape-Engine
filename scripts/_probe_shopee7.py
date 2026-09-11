from pathlib import Path

t = Path("output/_shopee_fb.html").read_text(encoding="utf-8")
idx = t.find("ld+json")
print(t[idx - 50 : idx + 1500])
