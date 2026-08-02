def run_case(case_id):
    in_file = os.path.join(testdata_dir, input_pat.replace('#', str(case_id)))
    out_file = os.path.join(testdata_dir, output_pat.replace('#', str(case_id)))
 
    # 读取输入
    inp = ''
    if os.path.exists(in_file):
        with open(in_file) as f:
            inp = f.read()
 
    # 读取期望输出
    expected = ''
    if os.path.exists(out_file):
        with open(out_file) as f:
            expected = f.read()
 
    if not os.path.exists(in_file):
        return {'status': TASK_FAILED, 'result': {'type': RUNTIME_ERROR, 'time': 0, 'memory': 0, 'scoringRate': 0, 'input': None, 'output': None, 'userOutput': None, 'userError': None}}
 
    case_dir = tempfile.mkdtemp()
    user_out = ''
    user_err = ''
    try:
        # 交互题
        if problem_type == 'interaction' and interactor_bin:
            shutil.copy2(in_file, os.path.join(case_dir, 'input'))
            start = tmod.time()
            try:
                inter_proc = subprocess.Popen(
                    [interactor_bin],
                    cwd=case_dir,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                user_proc = subprocess.Popen(
                    lang_cfg['run'],
                    cwd=workdir,
                    stdin=inter_proc.stdout,
                    stdout=inter_proc.stdin,
                    stderr=subprocess.PIPE
                )
                inter_proc.stdin.close()
                inter_proc.stdout.close()
 
                user_out_bytes, user_err = user_proc.communicate(timeout=time_limit/1000+1)
                inter_out, inter_err = inter_proc.communicate(timeout=5)
                elapsed = int((tmod.time() - start) * 1000)
                user_out = user_out_bytes.decode('utf-8', errors='replace') if isinstance(user_out_bytes, bytes) else user_out_bytes
 
                if user_proc.returncode != 0:
                    return {'status': TASK_DONE, 'result': {'type': RUNTIME_ERROR, 'time': elapsed, 'memory': 0, 'scoringRate': 0, 'input': {'name': f'{case_id}.in', 'content': inp}, 'output': {'name': f'{case_id}.out', 'content': expected}, 'userOutput': user_out, 'userError': user_err.decode('utf-8', errors='replace') if isinstance(user_err, bytes) else str(user_err)}}
 
                score_file = os.path.join(case_dir, 'score.txt')
                if os.path.exists(score_file):
                    with open(score_file) as f:
                        score_val = float(f.read().strip())
                else:
                    score_val = 0
                scoring_rate = score_val / 100
                if scoring_rate >= 1.0:
                    tc_type = ACCEPTED
                elif scoring_rate > 0:
                    tc_type = PARTIALLY_CORRECT
                else:
                    tc_type = WRONG_ANSWER
                spj_msg = inter_err.decode('utf-8', errors='replace') if isinstance(inter_err, bytes) else str(inter_err)
                return {'status': TASK_DONE, 'result': {'type': tc_type, 'time': elapsed, 'memory': 0, 'scoringRate': scoring_rate, 'input': {'name': f'{case_id}.in', 'content': inp}, 'output': {'name': f'{case_id}.out', 'content': expected}, 'userOutput': user_out, 'userError': '', 'spjMessage': spj_msg}}
 
            except subprocess.TimeoutExpired:
                user_proc.kill()
                inter_proc.kill()
                return {'status': TASK_DONE, 'result': {'type': TIME_LIMIT_EXCEEDED, 'time': time_limit, 'memory': 0, 'scoringRate': 0, 'input': {'name': f'{case_id}.in', 'content': inp}, 'output': {'name': f'{case_id}.out', 'content': expected}, 'userOutput': '', 'userError': ''}}
 
        # 提交答案题
        if problem_type == 'submit-answer':
            if payload.get('extra_data'):
                ans_zip = base64.b64decode(payload['extra_data'])
                user_out_file = output_pat.replace('#', str(case_id))
                with zipfile.ZipFile(io.BytesIO(ans_zip)) as az:
                    try:
                        user_out = az.read(user_out_file).decode()
                    except KeyError:
                        for n in az.namelist():
                            if os.path.basename(n) == user_out_file:
                                user_out = az.read(n).decode()
                                break
                        else:
                            return {'status': TASK_DONE, 'result': {'type': WRONG_ANSWER, 'time': 0, 'memory': 0, 'scoringRate': 0, 'input': {'name': f'{case_id}.in', 'content': inp}, 'output': {'name': f'{case_id}.out', 'content': expected}, 'userOutput': '', 'userError': ''}}
            elapsed = 0
        else:
            # 传统题
            start = tmod.time()
            try:
                proc = subprocess.run(
                    lang_cfg['run'],
                    cwd=workdir,
                    input=inp, capture_output=True, text=True,
                    timeout=time_limit/1000+1
                )
                elapsed = int((tmod.time() - start) * 1000)
                user_out = proc.stdout
                user_err = proc.stderr
                if proc.returncode != 0:
                    return {'status': TASK_DONE, 'result': {'type': RUNTIME_ERROR, 'time': elapsed, 'memory': 0, 'scoringRate': 0, 'input': {'name': f'{case_id}.in', 'content': inp}, 'output': {'name': f'{case_id}.out', 'content': expected}, 'userOutput': user_out, 'userError': user_err}}
                if elapsed > time_limit:
                    return {'status': TASK_DONE, 'result': {'type': TIME_LIMIT_EXCEEDED, 'time': elapsed, 'memory': 0, 'scoringRate': 0, 'input': {'name': f'{case_id}.in', 'content': inp}, 'output': {'name': f'{case_id}.out', 'content': expected}, 'userOutput': user_out, 'userError': user_err}}
            except subprocess.TimeoutExpired:
                return {'status': TASK_DONE, 'result': {'type': TIME_LIMIT_EXCEEDED, 'time': time_limit, 'memory': 0, 'scoringRate': 0, 'input': {'name': f'{case_id}.in', 'content': inp}, 'output': {'name': f'{case_id}.out', 'content': expected}, 'userOutput': '', 'userError': ''}}
 
        # SPJ 判断
        if spj_bin:
            user_out_file = os.path.join(case_dir, 'user_out')
            with open(user_out_file, 'w') as f:
                f.write(user_out)
            spj_input = os.path.join(case_dir, 'input')
            spj_answer = os.path.join(case_dir, 'answer')
            spj_code = os.path.join(case_dir, 'code')
            shutil.copy2(in_file, spj_input)
            if os.path.exists(out_file):
                shutil.copy2(out_file, spj_answer)
            with open(spj_code, 'w') as f:
                f.write(code)
            sp = subprocess.run(
                [spj_bin],
                cwd=case_dir,
                capture_output=True, text=True, timeout=10
            )
            try:
                scoring_rate = float(sp.stdout.strip()) / 100
            except:
                scoring_rate = 0
            if scoring_rate >= 1.0:
                tc_type = ACCEPTED
            elif scoring_rate > 0:
                tc_type = PARTIALLY_CORRECT
            else:
                tc_type = WRONG_ANSWER
            return {'status': TASK_DONE, 'result': {'type': tc_type, 'time': elapsed, 'memory': 0, 'scoringRate': scoring_rate, 'input': {'name': f'{case_id}.in', 'content': inp}, 'output': {'name': f'{case_id}.out', 'content': expected}, 'userOutput': user_out, 'userError': user_err, 'spjMessage': sp.stderr}}
        else:
            # 文本比较
            if not os.path.exists(out_file):
                return {'status': TASK_DONE, 'result': {'type': WRONG_ANSWER, 'time': elapsed, 'memory': 0, 'scoringRate': 0, 'input': {'name': f'{case_id}.in', 'content': inp}, 'output': None, 'userOutput': user_out, 'userError': user_err}}
            ac = user_out.rstrip() == expected.rstrip()
            tc_type = ACCEPTED if ac else WRONG_ANSWER
            return {'status': TASK_DONE, 'result': {'type': tc_type, 'time': elapsed, 'memory': 0, 'scoringRate': 1.0 if ac else 0.0, 'input': {'name': f'{case_id}.in', 'content': inp}, 'output': {'name': f'{case_id}.out', 'content': expected}, 'userOutput': user_out, 'userError': user_err}}
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)
