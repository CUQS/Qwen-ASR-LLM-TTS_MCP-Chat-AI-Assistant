import os
import sys
from fugashi import Tagger

# 报错的路径
dic_dir = r"D:\uv_venv\qwen-asr\Lib\site-packages\unidic\dicdir"
mecabrc = os.path.join(dic_dir, "mecabrc")

print(f"Checking paths...")
print(f"dic_dir exists: {os.path.exists(dic_dir)}")
print(f"mecabrc exists: {os.path.exists(mecabrc)}")

args = f'-C -r "{mecabrc}" -d "{dic_dir}"'
print(f"Attempting Tagger with absolute paths: {args}")
try:
    tagger = Tagger(args)
    print("Success with absolute paths!")
except Exception as e:
    print(f"Failed with absolute paths: {e}")

print("\nAttempting Tagger with relative paths (changing CWD)...")
old_cwd = os.getcwd()
try:
    os.chdir(dic_dir)
    # 在当前目录下使用相对路径
    tagger = Tagger('-r mecabrc -d .')
    print("Success with relative paths!")
except Exception as e:
    print(f"Failed with relative paths: {e}")
finally:
    os.chdir(old_cwd)
