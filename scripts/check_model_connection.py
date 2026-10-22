"""Explicit, minimal provider smoke test. Never starts an exam or prints keys."""
import argparse
import json
from courseagent.agent_roles import ROLE, ROLES
from courseagent.model_client import _chat_json_langchain, configuration, validate_runtime_settings


def main(argv=None):
    parser = argparse.ArgumentParser(description='读取本地配置，通过 LangChain 发起一次最小 JSON 请求；不组卷、不操作头歌。')
    parser.add_argument('--role', choices=ROLES, help='检查某个角色的最终配置（含角色覆盖）')
    parser.add_argument('--check-only', action='store_true', help='只检查配置，不发送请求')
    args = parser.parse_args(argv)
    token = ROLE.set(args.role)
    try:
        config = configuration()
        if not all(config.get(k) for k in ('base_url', 'model', 'api_key')):
            raise ValueError('请先填写 base_url、model 和 api_key')
        from urllib.parse import urlparse
        url = urlparse(config['base_url'])
        if url.scheme != 'https' or not url.netloc or url.username or url.password or url.query or url.fragment:
            raise ValueError('base_url 应为 HTTPS API 前缀，不含账号密码、查询参数或片段')
        if not isinstance(config.get('json_mode', True), bool):
            raise ValueError('json_mode 必须为 true 或 false')
        validate_runtime_settings(config)
        # Do not print endpoints or config values; they can contain sensitive text.
        if args.check_only:
            print('配置格式检查通过；尚未验证接口和模型权限。')
            return 0
        metrics = {}
        result = _chat_json_langchain('连接测试：只返回 JSON 对象 {"ok":true}。',
                                     {'connection_test': True}, metrics,
                                     timeout=30, max_retries=0, max_tokens=64)
        if result.get('ok') is not True:
            raise ValueError('接口有响应，但未通过约定 JSON 内容检查')
        print(json.dumps({'ok': True, 'backend': 'langchain', 'role': args.role or 'default',
                          'usage': metrics}, ensure_ascii=False))
        return 0
    except (ValueError, OSError) as error:
        # Only local validation errors may be shown; provider response bodies never are.
        if isinstance(error, ValueError) and str(error).startswith(('model-config.local.json', '模型配置必须', '请先填写', 'base_url 应', 'json_mode 必须', '接口有响应', '模型尚未配置', '模型接口地址必须', 'streaming 必须', 'timeout_seconds 必须', 'max_output_tokens 必须', 'token_parameter 必须', 'roles 必须', '角色配置必须')):
            print(str(error))
        else:
            print('连接测试失败：配置读取或响应 JSON 格式错误。')
        return 1
    except Exception as error:
        status = getattr(error, 'status_code', None)
        hints = {400: '检查模型名和 JSON 模式参数', 401: '检查密钥', 402: '检查中转账户余额',
                 403: '检查模型权限', 404: '检查 API 前缀及模型名', 429: '检查限流或额度'}
        if type(status) is int:
            print('连接测试失败：HTTP ' + str(status) + '；' + hints.get(status, '检查服务状态') + '。')
        else:
            print('连接测试失败：检查依赖、网络、接口地址或响应格式；未输出服务端原文。')
        return 1
    finally:
        ROLE.reset(token)


if __name__ == '__main__':
    raise SystemExit(main())
