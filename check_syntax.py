#!/usr/bin/env python
"""全面 JS 语法检查 — 检查所有 HTML/JS 文件中的脚本块无语法错误"""
import subprocess, sys, json, tempfile, os
from pathlib import Path

BASE = Path(__file__).parent

TARGETS = [
    "dist/index.html",
    "index_master.html",
    "dist/triple_resonance.html",
]

JS_SCRIPT = """
var fs = require('fs');
var stdin = fs.readFileSync(0, 'utf-8');
var files = JSON.parse(stdin);
var errors = 0;

function checkFile(fp) {
  if (!fs.existsSync(fp)) { console.log('SKIP (not found): ' + fp); return 0; }
  var html = fs.readFileSync(fp, 'utf-8');
  var re = /<script[^>]*>([\\s\\S]*?)<\\/script>/gi;
  var blockNum = 0, localErrors = 0, match;
  while ((match = re.exec(html)) !== null) {
    blockNum++;
    var code = match[1].trim();
    if (!code) continue;
    try { new Function(code); } catch(e) {
      console.log('  SYNTAX ERROR ' + fp + ' Block#' + blockNum + ' line ' + (e.lineNumber||'?') + ': ' + e.message);
      localErrors++;
    }
  }
  if (localErrors === 0) console.log('  PASS: ' + fp);
  return localErrors;
}

for (var i = 0; i < files.length; i++) errors += checkFile(files[i]);
if (errors === 0) console.log('  ALL CLEAN');
process.exit(errors > 0 ? 1 : 0);
"""

def check():
    try:
        proc = subprocess.run(
            ["node", "-e", JS_SCRIPT],
            cwd=str(BASE), input=json.dumps(TARGETS),
            capture_output=True, text=True, timeout=30
        )
        if proc.stdout:
            print(proc.stdout)
        if proc.returncode != 0:
            if proc.stderr:
                print(proc.stderr.strip(), file=sys.stderr)
        return proc.returncode
    except Exception as e:
        print(f"check_syntax error: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    rc = check()
    sys.exit(rc)
