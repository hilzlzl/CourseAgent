"""Linux bubblewrap executor. Never fall back to running generated code on host."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
from courseagent.tool_registry import registered_tool, ToolPolicy
from courseagent.agent_contracts import ExecuteInput, ExecuteOutput
from courseagent.observability import span

LIMIT = 65536
WRAPPER = '''import resource, runpy
resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
resource.setrlimit(resource.RLIMIT_AS, (268435456, 268435456))
resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
runpy.run_path('/work/solution.py', run_name='__main__')
'''


def execute(code, stdin='', timeout=5, output_limit=LIMIT):
    if type(output_limit) is not int or not LIMIT <= output_limit <= 4*1024*1024:
        raise ValueError('执行输出额度不正确')
    if not isinstance(code, str) or not code.strip() or len(code) > 50000:
        raise ValueError('参考程序缺失或过长')
    if not isinstance(stdin, str) or len(stdin.encode()) > LIMIT:
        raise ValueError('测试输入超过执行上限')
    executable = shutil.which('bwrap')
    if not executable or not Path('/usr/bin/python3').exists():
        return {'ok': False, 'status': 'unavailable', 'output': '', 'error': '本机未配置隔离执行环境'}
    with tempfile.TemporaryDirectory(prefix='educoder-sandbox-') as folder:
        root = Path(folder)
        (root / 'solution.py').write_text(code, encoding='utf-8')
        (root / 'runner.py').write_text(WRAPPER.replace('(65536, 65536)',f'({output_limit}, {output_limit})'), encoding='utf-8')
        root.chmod(0o755)
        cmd = [executable, '--unshare-all', '--die-with-parent', '--new-session',
               '--cap-drop', 'ALL', '--uid', '65534', '--gid', '65534',
               '--clearenv', '--setenv', 'PATH', '/usr/bin',
               '--ro-bind', '/usr', '/usr']
        for p in ('/lib', '/lib64'):
            if Path(p).exists():
                cmd += ['--ro-bind', p, p]
        cmd += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                '--ro-bind', folder, '/work', '--chdir', '/work',
                '/usr/bin/python3', '-I', '-B', '/work/runner.py']
        with (root / 'stdout').open('wb') as out, (root / 'stderr').open('wb') as err:
            child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                     start_new_session=True, env={'PATH': '/usr/bin:/bin'})
            try:
                child.communicate(stdin.encode(), timeout=max(1, min(timeout, 10)))
                status = 'passed' if child.returncode == 0 else 'execution_error'
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.communicate()
                status = 'timeout'
        output = (root / 'stdout').read_bytes()[:output_limit].decode('utf-8', errors='replace')
        error = (root / 'stderr').read_bytes()[:4000].decode('utf-8', errors='replace')
        return {'ok': status == 'passed', 'status': status, 'output': output,
                'error': error, 'returncode': child.returncode}


def available():
    return execute('print("sandbox-ready")').get('output', '').strip() == 'sandbox-ready'


@registered_tool(ExecuteInput, ExecuteOutput, policy=ToolPolicy(side_effect="isolated_execution", boundary="networkless_sandbox"))
def execute_python_reference(code: str, stdin: str = '', output_limit: int = LIMIT) -> dict:
    """Execute a private Python stdin/stdout reference in a networkless isolated sandbox."""
    with span('tool_execute_python_reference', 'tool') as metrics:
        result = execute(code, stdin, output_limit=output_limit)
        metrics.update(status=result['status'], input_chars=len(stdin))
        return result
