"""Local supervisor: separate API and Worker processes, restart either on failure."""
from courseagent.paths import ROOT as WORKSPACE_ROOT
import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
ROOT=WORKSPACE_ROOT


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);args=parser.parse_args()
    from courseagent.workspace_setup import initialize_workspace
    initialize_workspace(ROOT)
    children={};stopping=False
    commands={'api':[sys.executable,'-m','courseagent.api_service','--port',str(args.port)],
              'worker':[sys.executable,'-m','courseagent.agent_worker']}
    def stop(*unused):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    try:
        while not stopping:
            for name,command in commands.items():
                process=children.get(name)
                if process is None or process.poll() is not None:
                    print('Starting '+name,flush=True)
                    children[name]=subprocess.Popen(command,cwd=ROOT,env=os.environ.copy(),start_new_session=True)
            time.sleep(1)
    finally:
        for process in children.values():
            if process.poll() is None:process.terminate()
        for process in children.values():
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()

if __name__=='__main__':main()
