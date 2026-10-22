"""Compile and run source programs inside bubblewrap; never execute on host.

Compiled artifacts are cached only within this worker process. Missing compiler
is an explicit capability miss, not permission to bypass isolation.
"""
import hashlib
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
from functools import lru_cache

_CACHE=tempfile.TemporaryDirectory(prefix='educoder-compiled-')
Path(_CACHE.name).chmod(0o755)
_LOCK=threading.RLock()
_LANGS={'C':('gcc','solution.c'), 'C++':('g++','solution.cpp'), 'Java':('javac','Main.java')}


@lru_cache(maxsize=1)
def java_compiler():
    if shutil.which('javac'):return 'javac'
    if shutil.which('java'):
        try:
            result=subprocess.run(['java','--list-modules'],capture_output=True,timeout=3)
            if b'jdk.compiler@' in result.stdout:return 'java'
        except (OSError,subprocess.TimeoutExpired):pass
    return None


def available(language):
    if language=='Python':
        from courseagent.code_sandbox import available as python_available
        return python_available()
    compiler=java_compiler() if language=='Java' else _LANGS.get(language,('',))[0]
    return language in _LANGS and bool(shutil.which('bwrap') and compiler and shutil.which(compiler) and (language!='Java' or shutil.which('java')))


def _run(folder,command,stdin,timeout,output_limit,compile_step=False):
    mount='/build' if compile_step else '/work'
    cmd=[shutil.which('bwrap'),'--unshare-all','--die-with-parent','--new-session','--cap-drop','ALL',
         '--uid','65534','--gid','65534','--clearenv','--setenv','PATH','/usr/bin:/bin',
         '--ro-bind','/usr','/usr']
    for path in ('/lib','/lib64'):
        if Path(path).exists():cmd+=['--ro-bind',path,path]
    # JVM uses these system files; no application config or home is exposed.
    for path in ('/etc/alternatives','/etc/java-21-openjdk','/etc/ld.so.cache'):
        if Path(path).exists():cmd+=['--ro-bind',path,path]
    cpu=15 if compile_step else 3
    memory=1536*1024*1024 if compile_step or command[0]=='java' else 256*1024*1024
    wrapper=('import os,resource;'
             f'resource.setrlimit(resource.RLIMIT_CPU,({cpu},{cpu}));'
             f'resource.setrlimit(resource.RLIMIT_AS,({memory},{memory}));'
             f'resource.setrlimit(resource.RLIMIT_FSIZE,({16*1024*1024 if compile_step else output_limit},)*2);'
             'resource.setrlimit(resource.RLIMIT_NOFILE,(64,64));'
             f'resource.setrlimit(resource.RLIMIT_NPROC,({64 if compile_step or command[0]=="java" else 0},)*2);'
             f'os.execvp({command[0]!r},{command!r})')
    cmd+=['--proc','/proc','--dev','/dev','--tmpfs','/tmp',
          '--bind' if compile_step else '--ro-bind',str(folder),mount,'--chdir',mount,
          '/usr/bin/python3','-I','-c',wrapper]
    with tempfile.TemporaryFile() as out,tempfile.TemporaryFile() as err:
        child=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=out,stderr=err,start_new_session=True,env={'PATH':'/usr/bin:/bin'})
        try:
            child.communicate(stdin.encode(),timeout=timeout)
            status='passed' if child.returncode==0 else 'execution_error'
        except subprocess.TimeoutExpired:
            os.killpg(child.pid,signal.SIGKILL);child.communicate();status='timeout'
        out.seek(0);err.seek(0);output=out.read(output_limit+1)
        if len(output)>output_limit:status='output_limit'
        return {'ok':status=='passed','status':status,'output':output[:output_limit].decode('utf-8',errors='replace'),
                'error':err.read(4000).decode('utf-8',errors='replace'),'returncode':child.returncode}


def execute(language,code,stdin='',timeout=5,output_limit=65536):
    if language=='Python':
        from courseagent.code_sandbox import execute as python_execute
        return python_execute(code,stdin,timeout,output_limit)
    if not isinstance(code,str) or not 1<=len(code)<=50000 or not isinstance(stdin,str) or len(stdin.encode())>65536:
        raise ValueError('程序或输入超出执行上限')
    if type(output_limit) is not int or not 65536<=output_limit<=4194304:raise ValueError('输出额度不正确')
    if not available(language):return {'ok':False,'status':'unavailable','output':'','error':'缺少隔离环境或该语言编译器'}
    compiler,filename=_LANGS[language]
    if language=='Java':compiler=java_compiler()
    identity=hashlib.sha256((language+'\0'+str(Path(shutil.which(compiler)).stat().st_mtime_ns)+'\0'+code).encode()).hexdigest()
    folder=Path(_CACHE.name)/identity
    artifact=folder/('Main.class' if language=='Java' else 'program')
    with _LOCK:
        hit=artifact.exists()
        if not hit:
            folder.mkdir(exist_ok=True);folder.chmod(0o777)
            (folder/filename).write_text(code,encoding='utf-8')
            java_options=['-Xmx256m','-XX:ReservedCodeCacheSize=32m','-XX:CompressedClassSpaceSize=32m','-XX:+UseSerialGC']
            command=(([compiler]+['-J'+flag for flag in java_options]+['Main.java'] if compiler=='javac' else
                      ['java']+java_options+['-m','jdk.compiler/com.sun.tools.javac.Main','Main.java']) if language=='Java'
                     else [compiler,'-O2','-pipe','-std=c++17' if language=='C++' else '-std=c11',filename,'-o','program'])
            result=_run(folder,command,'',20,65536,True)
            if not result['ok'] or not artifact.exists():return {**result,'ok':False,'status':'compile_error','compile_cache_hit':False}
            # No source-controlled files may be written during test execution.
            folder.chmod(0o755)
    command=(['java','-Xmx128m','-XX:ReservedCodeCacheSize=32m','-XX:CompressedClassSpaceSize=32m','-XX:+UseSerialGC','-cp','/work','Main']
             if language=='Java' else ['/work/program'])
    return {**_run(folder,command,stdin,max(1,min(timeout,10)),output_limit),'compile_cache_hit':hit}


from courseagent.tool_registry import registered_tool,ToolPolicy
from courseagent.agent_contracts import NativeExecuteInput,NativeExecuteOutput

@registered_tool(NativeExecuteInput,NativeExecuteOutput,policy=ToolPolicy(side_effect='isolated_execution',boundary='networkless_sandbox'))
def execute_source_reference(language: str,code: str,stdin: str='',output_limit: int=65536) -> dict:
    """Compile/cache and execute a literal source reference inside networkless isolation."""
    return execute(language,code,stdin,output_limit=output_limit)
