import json
import os
import subprocess
import base64
import zipfile
import io
import tempfile
import shutil
import sys
import yaml
import time as tmod
import re
import threading
 
judge_id = os.environ['JUDGE_ID']
payload_file = os.environ['PAYLOAD_FILE']
testdata_file = os.environ['TESTDATA_FILE']
 
print(f"[Judge] Starting judge_id={judge_id}")
 
with open(payload_file) as f:
    payload = json.load(f)
 
language = payload.get('language', 'cpp')
code = payload.get('code', '')
time_limit = int(payload.get('time_limit', 1000))
memory_limit = int(payload.get('memory_limit', 256))
problem_type = payload.get('problem_type', 'traditional')
 
print(f"[Judge] language={language} problem_type={problem_type} time_limit={time_limit}")
 
# SYZOJ TestcaseResultType
ACCEPTED = 1
WRONG_ANSWER = 2
PARTIALLY_CORRECT = 3
MEMORY_LIMIT_EXCEEDED = 4
TIME_LIMIT_EXCEEDED = 5
OUTPUT_LIMIT_EXCEEDED = 6
FILE_ERROR = 7
RUNTIME_ERROR = 8
JUDGEMENT_FAILED = 9
INVALID_INTERACTION = 10
 
# SYZOJ TaskStatus
TASK_DONE = 2
TASK_FAILED = 3
 
workdir = tempfile.mkdtemp()
testdata_dir = os.path.join(workdir, 'testdata')
os.makedirs(testdata_dir, exist_ok=True)
 
if os.path.exists(testdata_file):
    with zipfile.ZipFile(testdata_file) as z:
        z.extractall(testdata_dir)
    print(f"[Judge] Testdata extracted: {os.listdir(testdata_dir)}")
else:
    print(f"[Judge] No testdata file found at {testdata_file}")
 
LANG = {
    'cpp':     {'ext': 'cpp', 'compile': ['g++', '-O2', '-std=c++17', '-finput-charset=UTF-8', '-fexec-charset=UTF-8', '-o', 'sol', 'sol.cpp'], 'run': ['./sol']},
    'cpp11':   {'ext': 'cpp', 'compile': ['g++', '-O2', '-std=c++11', '-finput-charset=UTF-8', '-fexec-charset=UTF-8', '-o', 'sol', 'sol.cpp'], 'run': ['./sol']},
    'cpp17':   {'ext': 'cpp', 'compile': ['g++', '-O2', '-std=c++17', '-finput-charset=UTF-8', '-fexec-charset=UTF-8', '-o', 'sol', 'sol.cpp'], 'run': ['./sol']},
    'c':       {'ext': 'c',   'compile': ['gcc', '-O2', '-finput-charset=UTF-8', '-fexec-charset=UTF-8', '-o', 'sol', 'sol.c'], 'run': ['./sol']},
    'python3': {'ext': 'py',  'compile': None, 'run': ['python3', 'sol.py']},
    'python2': {'ext': 'py',  'compile': None, 'run': ['python2', 'sol.py']},
    'java':    {'ext': 'java','compile': ['javac', 'sol.java'], 'run': ['java', 'sol']},
    'pascal':  {'ext': 'pas', 'compile': ['fpc', 'sol.pas'], 'run': ['./sol']},
    'ruby':    {'ext': 'rb',  'compile': None, 'run': ['ruby', 'sol.rb']},
    'haskell': {'ext': 'hs',  'compile': ['ghc', '-O2', '-o', 'sol', 'sol.hs'], 'run': ['./sol']},
    'nodejs':  {'ext': 'js',  'compile': None, 'run': ['node', 'sol.js']},
}
 
lang_cfg = LANG.get(language, LANG['cpp'])
src_file = os.path.join(workdir, f"sol.{lang_cfg['ext']}")
 
with open(src_file, 'w', encoding='utf-8') as f:
    f.write(code)
 
result = {
    'compile': None,
    'judge': {'subtasks': []},
    'error': None
}
 
# Truncate helpers
def truncate(s, maxlen=2000):
    if s is None:
        return None
    if len(s) <= maxlen:
        return s
    return s[:maxlen] + '\n... (truncated, total %d chars)' % len(s)
 
# Compile
if lang_cfg['compile']:
    try:
        cp = subprocess.run(
            lang_cfg['compile'],
            cwd=workdir,
            capture_output=True, text=True, timeout=30
        )
        compile_status = TASK_DONE if cp.returncode == 0 else TASK_FAILED
        compile_msg = cp.stdout + cp.stderr
        result['compile'] = {'status': compile_status, 'message': compile_msg}
        print(f"[Judge] Compile status={compile_status} msg={compile_msg[:100]}")
        if cp.returncode != 0:
            with open('result.json', 'w') as f:
                json.dump(result, f)
            print("[Judge] Compile error, exiting")
            sys.exit(0)
    except Exception as e:
        result['compile'] = {'status': TASK_FAILED, 'message': str(e)}
        with open('result.json', 'w') as f:
            json.dump(result, f)
        print(f"[Judge] Compile exception: {e}")
        sys.exit(0)
 
# Read data.yml
data_yml_path = os.path.join(testdata_dir, 'data.yml')
subtasks = []
input_pat = '#.in'
output_pat = '#.out'
spj_lang = None
spj_file = None
interactor_lang = None
interactor_file = None
extra_source_files = []
 
if os.path.exists(data_yml_path):
    with open(data_yml_path) as f:
        dy = yaml.safe_load(f) or {}
    input_pat = dy.get('inputFile', '#.in')
    output_pat = dy.get('outputFile', dy.get('answerFile', '#.out'))
    if dy.get('specialJudge'):
        spj_lang = dy['specialJudge']['language']
        spj_file = dy['specialJudge']['fileName']
    if dy.get('interactor'):
        interactor_lang = dy['interactor']['language']
        interactor_file = dy['interactor']['fileName']
    if dy.get('extraSourceFiles'):
        extra_source_files = dy['extraSourceFiles']
    if dy.get('subtasks'):
        for st in dy['subtasks']:
            subtasks.append({
                'score': st['score'],
                'type': st.get('type', 'sum'),
                'cases': [str(c) for c in st['cases']]
            })
    if problem_type == 'submit-answer' and dy.get('userOutput'):
        output_pat = dy['userOutput']
    print(f"[Judge] data.yml loaded: subtasks={len(subtasks)} input_pat={input_pat} output_pat={output_pat}")
 
# Auto detect testcases
if not subtasks:
    td_files = os.listdir(testdata_dir)
    ins = sorted([f for f in td_files if f.endswith('.in')])
    cases = [inf[:-3] for inf in ins]
    if cases:
        subtasks = [{'score': 100, 'type': 'sum', 'cases': cases}]
        has_out = any(f.endswith('.out') for f in td_files)
        input_pat = '#.in'
        output_pat = '#.out' if has_out else '#.ans'
    print(f"[Judge] Auto detected: cases={cases} output_pat={output_pat}")
 
# Detect SPJ
if not spj_file:
    for f in os.listdir(testdata_dir):
        if f.startswith('spj_'):
            parts = f[4:].split('.')
            spj_lang = parts[0]
            spj_file = f
            break
 
# Compile SPJ
spj_bin = None
if spj_file:
    spj_path = os.path.join(testdata_dir, spj_file)
    if spj_lang == 'cpp':
        spj_bin = os.path.join(workdir, 'spj')
        subprocess.run(['g++', '-O2', '-o', spj_bin, spj_path], cwd=workdir, capture_output=True)
    elif spj_lang == 'c':
        spj_bin = os.path.join(workdir, 'spj')
        subprocess.run(['gcc', '-O2', '-o', spj_bin, spj_path], cwd=workdir, capture_output=True)
    elif spj_lang == 'python3':
        spj_bin = spj_path
    print(f"[Judge] SPJ: {spj_file}, lang={spj_lang}, bin={spj_bin}")
 
# Compile interactor
interactor_bin = None
if interactor_file:
    interactor_path = os.path.join(testdata_dir, interactor_file)
    interactor_bin = os.path.join(workdir, 'interactor')
    if interactor_lang in ('cpp', 'c'):
        cc = 'g++' if interactor_lang == 'cpp' else 'gcc'
        subprocess.run([cc, '-O2', '-o', interactor_bin, interactor_path], cwd=workdir, capture_output=True)
    print(f"[Judge] Interactor: {interactor_file}, bin={interactor_bin}")
 
# Copy extra source files
for esf in extra_source_files:
    if esf.get('language') == language:
        for fobj in esf.get('files', []):
            src = os.path.join(testdata_dir, fobj['name'])
            dst = os.path.join(workdir, fobj['dest'])
            if os.path.exists(src):
                shutil.copy2(src, dst)
 
 
def run_case(case_id):
    in_file = os.path.join(testdata_dir, input_pat.replace('#', str(case_id)))
    out_file = os.path.join(testdata_dir, output_pat.replace('#', str(case_id)))
 
    inp = ''
    if os.path.exists(in_file):
        with open(in_file) as f:
            inp = f.read()
 
    expected = ''
    if os.path.exists(out_file):
        with open(out_file) as f:
            expected = f.read()
 
    if not os.path.exists(in_file):
        return {'status': TASK_FAILED, 'result': {
            'type': RUNTIME_ERROR, 'time': 0, 'memory': 0, 'scoringRate': 0,
            'input': None, 'output': None, 'userOutput': None, 'userError': None
        }}
 
    case_dir = tempfile.mkdtemp()
    user_out = ''
    user_err = ''
 
    try:
        # Interactive problem
        if problem_type == 'interaction' and interactor_bin:
            shutil.copy2(in_file, os.path.join(case_dir, 'input'))
            start = tmod.time()
            try:
                user_proc = subprocess.Popen(
                    lang_cfg['run'], cwd=workdir,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                inter_proc = subprocess.Popen(
                    [interactor_bin], cwd=case_dir,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
 
                # 线程转发: user stdout -> interactor stdin
                def pipe_u2i():
                    try:
                        while True:
                            data = user_proc.stdout.read(4096)
                            if not data:
                                break
                            inter_proc.stdin.write(data)
                    except:
                        pass
                    finally:
                        try:
                            inter_proc.stdin.close()
                        except:
                            pass
 
                # 线程转发: interactor stdout -> user stdin
                def pipe_i2u():
                    try:
                        while True:
                            data = inter_proc.stdout.read(4096)
                            if not data:
                                break
                            user_proc.stdin.write(data)
                    except:
                        pass
                    finally:
                        try:
                            user_proc.stdin.close()
                        except:
                            pass
 
                t1 = threading.Thread(target=pipe_u2i)
                t2 = threading.Thread(target=pipe_i2u)
                t1.start()
                t2.start()
 
                # 等待选手进程结束
                user_proc.wait(timeout=time_limit / 1000 + 2)
                elapsed = int((tmod.time() - start) * 1000)
 
                # 等待交互库结束
                try:
                    inter_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    inter_proc.kill()
 
                t1.join(timeout=5)
                t2.join(timeout=5)
 
                user_err_b = user_proc.stderr.read()
                inter_err_b = inter_proc.stderr.read()
                user_err = user_err_b.decode('utf-8', errors='replace') if isinstance(user_err_b, bytes) else str(user_err_b)
                inter_err = inter_err_b.decode('utf-8', errors='replace') if isinstance(inter_err_b, bytes) else str(inter_err_b)
 
                if user_proc.returncode != 0:
                    return {'status': TASK_DONE, 'result': {
                        'type': RUNTIME_ERROR, 'time': elapsed, 'memory': 0, 'scoringRate': 0,
                        'input': {'name': f'{case_id}.in', 'content': inp},
                        'output': {'name': f'{case_id}.out', 'content': expected},
                        'userOutput': '', 'userError': user_err
                    }}
 
                if elapsed > time_limit:
                    return {'status': TASK_DONE, 'result': {
                        'type': TIME_LIMIT_EXCEEDED, 'time': elapsed, 'memory': 0, 'scoringRate': 0,
                        'input': {'name': f'{case_id}.in', 'content': inp},
                        'output': {'name': f'{case_id}.out', 'content': expected},
                        'userOutput': '', 'userError': user_err
                    }}
 
                score_file = os.path.join(case_dir, 'score.txt')
                if os.path.exists(score_file):
                    score_val = float(open(score_file).read().strip())
                else:
                    score_val = 0
                scoring_rate = score_val / 100
                tc_type = ACCEPTED if scoring_rate >= 1.0 else (PARTIALLY_CORRECT if scoring_rate > 0 else WRONG_ANSWER)
 
                return {'status': TASK_DONE, 'result': {
                    'type': tc_type, 'time': elapsed, 'memory': 0, 'scoringRate': scoring_rate,
                    'input': {'name': f'{case_id}.in', 'content': inp},
                    'output': {'name': f'{case_id}.out', 'content': expected},
                    'userOutput': '', 'userError': user_err, 'spjMessage': inter_err
                }}
            except subprocess.TimeoutExpired:
                user_proc.kill()
                inter_proc.kill()
                t1.join(timeout=2)
                t2.join(timeout=2)
                return {'status': TASK_DONE, 'result': {
                    'type': TIME_LIMIT_EXCEEDED, 'time': time_limit, 'memory': 0, 'scoringRate': 0,
                    'input': {'name': f'{case_id}.in', 'content': inp},
                    'output': {'name': f'{case_id}.out', 'content': expected},
                    'userOutput': '', 'userError': ''
                }}
 
        # Submit-answer problem
        if problem_type == 'submit-answer':
            if payload.get('extra_data'):
                ans_zip = base64.b64decode(payload['extra_data'])
                user_out_filename = output_pat.replace('#', str(case_id))
                with zipfile.ZipFile(io.BytesIO(ans_zip)) as az:
                    try:
                        user_out = az.read(user_out_filename).decode()
                    except KeyError:
                        for n in az.namelist():
                            if os.path.basename(n) == user_out_filename:
                                user_out = az.read(n).decode()
                                break
                        else:
                            return {'status': TASK_DONE, 'result': {
                                'type': WRONG_ANSWER, 'time': 0, 'memory': 0, 'scoringRate': 0,
                                'input': {'name': f'{case_id}.in', 'content': inp},
                                'output': {'name': f'{case_id}.out', 'content': expected},
                                'userOutput': '', 'userError': ''
                            }}
            elapsed = 0
        else:
            # Traditional problem
            start = tmod.time()
            try:
                proc = subprocess.run(
                    lang_cfg['run'], cwd=workdir,
                    input=inp, capture_output=True, text=True,
                    timeout=time_limit / 1000 + 2
                )
                elapsed = int((tmod.time() - start) * 1000)
                user_out = proc.stdout
                user_err = proc.stderr
                if proc.returncode != 0:
                    return {'status': TASK_DONE, 'result': {
                        'type': RUNTIME_ERROR, 'time': elapsed, 'memory': 0, 'scoringRate': 0,
                        'input': {'name': f'{case_id}.in', 'content': inp},
                        'output': {'name': f'{case_id}.out', 'content': expected},
                        'userOutput': user_out, 'userError': user_err
                    }}
                if elapsed > time_limit:
                    return {'status': TASK_DONE, 'result': {
                        'type': TIME_LIMIT_EXCEEDED, 'time': elapsed, 'memory': 0, 'scoringRate': 0,
                        'input': {'name': f'{case_id}.in', 'content': inp},
                        'output': {'name': f'{case_id}.out', 'content': expected},
                        'userOutput': user_out, 'userError': user_err
                    }}
            except subprocess.TimeoutExpired:
                return {'status': TASK_DONE, 'result': {
                    'type': TIME_LIMIT_EXCEEDED, 'time': time_limit, 'memory': 0, 'scoringRate': 0,
                    'input': {'name': f'{case_id}.in', 'content': inp},
                    'output': {'name': f'{case_id}.out', 'content': expected},
                    'userOutput': '', 'userError': ''
                }}
 
        # SPJ judging
        if spj_bin:
            user_out_file = os.path.join(case_dir, 'user_out')
            with open(user_out_file, 'w') as f:
                f.write(user_out)
            shutil.copy2(in_file, os.path.join(case_dir, 'input'))
            if os.path.exists(out_file):
                shutil.copy2(out_file, os.path.join(case_dir, 'answer'))
            with open(os.path.join(case_dir, 'code'), 'w') as f:
                f.write(code)
            spj_cmd = ['python3', spj_bin] if spj_lang == 'python3' else [spj_bin]
            sp = subprocess.run(spj_cmd, cwd=case_dir, capture_output=True, text=True, timeout=60)
            print(f"[Judge] SPJ stdout: {sp.stdout.strip()}")
            print(f"[Judge] SPJ stderr: {sp.stderr.strip()}")
            try:
                scoring_rate = float(sp.stdout.strip()) / 100
            except Exception:
                scoring_rate = 0
            tc_type = ACCEPTED if scoring_rate >= 1.0 else (PARTIALLY_CORRECT if scoring_rate > 0 else WRONG_ANSWER)
            return {'status': TASK_DONE, 'result': {
                'type': tc_type, 'time': elapsed, 'memory': 0, 'scoringRate': scoring_rate,
                'input': {'name': f'{case_id}.in', 'content': inp},
                'output': {'name': f'{case_id}.out', 'content': expected},
                'userOutput': user_out, 'userError': user_err, 'spjMessage': sp.stderr
            }}
        else:
            if not os.path.exists(out_file):
                return {'status': TASK_DONE, 'result': {
                    'type': WRONG_ANSWER, 'time': elapsed, 'memory': 0, 'scoringRate': 0,
                    'input': {'name': f'{case_id}.in', 'content': inp},
                    'output': None, 'userOutput': user_out, 'userError': user_err
                }}
            ac = user_out.rstrip() == expected.rstrip()
            tc_type = ACCEPTED if ac else WRONG_ANSWER
            return {'status': TASK_DONE, 'result': {
                'type': tc_type, 'time': elapsed, 'memory': 0, 'scoringRate': 1.0 if ac else 0.0,
                'input': {'name': f'{case_id}.in', 'content': inp},
                'output': {'name': f'{case_id}.out', 'content': expected},
                'userOutput': user_out, 'userError': user_err
            }}
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)
 
 
# Run all subtasks
detail_subtasks = []
for idx, st in enumerate(subtasks):
    st_cases = []
    st_scores = []
    for cid in st['cases']:
        print(f"[Judge] Running case {cid}")
        r = run_case(cid)
        case_result = r['result']
        case_result['caseId'] = cid
 
        # Truncate long content
        for key in ['input', 'output']:
            if case_result.get(key) and isinstance(case_result[key], dict):
                if case_result[key].get('content'):
                    case_result[key]['content'] = truncate(case_result[key]['content'])
        for key in ['userOutput', 'userError']:
            if case_result.get(key):
                case_result[key] = truncate(case_result[key])
        if case_result.get('spjMessage'):
            case_result['spjMessage'] = truncate(case_result['spjMessage'])
 
        st_cases.append({'status': r['status'], 'result': case_result})
        st_scores.append(case_result.get('scoringRate', 0) * 100)
        print(f"[Judge] Case {cid} result: type={case_result['type']} time={case_result['time']}")
 
    if st['type'] == 'sum':
        st_score = st['score'] * sum(st_scores) / (100 * len(st_scores)) if st_scores else 0
    elif st['type'] == 'min':
        st_score = st['score'] * min(st_scores) / 100 if st_scores else 0
    elif st['type'] == 'mul':
        m = 1.0
        for s in st_scores:
            m *= s / 100
        st_score = st['score'] * m
    else:
        st_score = 0
 
    detail_subtasks.append({
        'id': idx,
        'score': st_score,
        'type': st['type'],
        'cases': st_cases
    })
    print(f"[Judge] Subtask {idx} score={st_score}")
 
result['judge'] = {'subtasks': detail_subtasks}
 
with open('result.json', 'w') as f:
    json.dump(result, f, indent=2)
 
print("[Judge] Done, result.json written.")
