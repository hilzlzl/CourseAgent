import json
from pathlib import Path
import tempfile
import unittest
from courseagent.native_sandbox import execute,available


class NativeSandboxTests(unittest.TestCase):
    @unittest.skipUnless(available('C++'),'C++ compiler or isolation unavailable')
    def test_compiled_reference_reuses_binary_and_cannot_read_project_files(self):
        with tempfile.TemporaryDirectory() as folder:
            sentinel=Path(folder)/'private-config.json'
            sentinel.write_text('private host file')
            self.assertTrue(sentinel.is_file())
            code='#include <iostream>\n#include <fstream>\nint main(){std::ifstream f('+json.dumps(str(sentinel))+');int x;std::cin>>x;std::cout<<(f.good()?-999:x+37);}'
            a=execute('C++',code,'5');b=execute('C++',code,'-2')
            self.assertTrue(a['ok'],a['error']);self.assertEqual(a['output'],'42')
            self.assertTrue(b['compile_cache_hit']);self.assertEqual(b['output'],'35')

    @unittest.skipUnless(available('C'),'C compiler or isolation unavailable')
    def test_c_program_and_compile_error(self):
        result=execute('C','#include <stdio.h>\nint main(){int a,b;scanf("%d%d",&a,&b);printf("%d",a+b);return 0;}','2 -4')
        self.assertTrue(result['ok'],result['error']);self.assertEqual(result['output'],'-2')
        self.assertEqual(execute('C','int main(){ broken }')['status'],'compile_error')

    @unittest.skipUnless(available('C++'),'C++ compiler or isolation unavailable')
    def test_timeout_is_bounded(self):
        result=execute('C++','int main(){while(true) {}}',timeout=1)
        self.assertFalse(result['ok']);self.assertIn(result['status'],('timeout','execution_error'))

    def test_missing_runtime_is_explicit(self):
        from unittest.mock import patch
        with patch('courseagent.native_sandbox.available',return_value=False):
            self.assertEqual(execute('Java','class Main { public static void main(String[] a){} }')['status'],'unavailable')

    @unittest.skipUnless(available('Java'),'Java compiler or isolation unavailable')
    def test_java_compilation_and_cached_execution(self):
        code='import java.util.*; public class Main { public static void main(String[] a){ Scanner s=new Scanner(System.in);System.out.println(s.nextInt()+1); } }'
        a=execute('Java',code,'41');b=execute('Java',code,'-2')
        self.assertTrue(a['ok'],a['error']);self.assertEqual(a['output'].strip(),'42')
        self.assertTrue(b['ok'],b['error']);self.assertTrue(b['compile_cache_hit']);self.assertEqual(b['output'].strip(),'-1')


if __name__=='__main__':unittest.main()
