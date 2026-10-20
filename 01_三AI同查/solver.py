"""固定并行调用三个通用模型，仅发送用户提供的当前题目。"""

import argparse
import base64
import json
import math
import os
import re
import sys
import struct
import zlib
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path


PROVIDERS = ('GPT', 'Qwen', 'DeepSeek')
IMAGE_PROMPT = '请识别图片中的题目及完整选项，并独立作答。图片不清晰或信息不足时请在理由中说明。'
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_SIDE = 8192
INSTRUCTIONS = (
    '请独立回答用户提供的题目，仅使用通用模型已有知识。'
    '不要读取文件、题库、知识库或调用任何工具。'
    '只返回 JSON 对象，格式为 {"answer":"答案","reason":"简短解答依据"}。'
    '选择题的 answer 只写选项字母，多选按字母顺序排列；判断题只写正确或错误；'
    '简答题写简洁答案。reason 用中文给出简要依据，不输出思考过程。'
)
ANSWER_SCHEMA = {
    'type': 'object',
    'properties': {'answer': {'type': 'string'}, 'reason': {'type': 'string'}},
    'required': ['answer', 'reason'],
    'additionalProperties': False,
}


@dataclass(frozen=True)
class Settings:
    openai_key: str = ''
    qwen_key: str = ''
    deepseek_key: str = ''
    qwen_base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    deepseek_base_url: str = 'https://api.deepseek.com'
    qwen_model: str = 'qwen3.8-max'
    deepseek_model: str = 'deepseek-flash'
    openai_base_url: str = 'https://api.openai.com/v1'
    openai_model: str = 'gpt-6.1-sol'
    openai_reasoning_effort: str = 'medium'
    qwen_reasoning_effort: str = 'off'
    deepseek_reasoning_effort: str = 'off'
    openai_proxy: str = ''
    timeout: float = 120

    @classmethod
    def from_env(cls, timeout=120):
        return cls(
            openai_key=os.getenv('OPENAI_API_KEY', ''),
            qwen_key=os.getenv('QWEN_API_KEY') or os.getenv('DASHSCOPE_API_KEY', ''),
            deepseek_key=os.getenv('DEEPSEEK_API_KEY', ''),
            qwen_base_url=os.getenv('QWEN_BASE_URL', cls.qwen_base_url),
            deepseek_base_url=os.getenv('DEEPSEEK_BASE_URL', cls.deepseek_base_url),
            qwen_model=os.getenv('QWEN_MODEL') or cls.qwen_model,
            deepseek_model=os.getenv('DEEPSEEK_MODEL') or cls.deepseek_model,
            qwen_reasoning_effort=os.getenv('QWEN_REASONING_EFFORT') or cls.qwen_reasoning_effort,
            deepseek_reasoning_effort=os.getenv('DEEPSEEK_REASONING_EFFORT') or cls.deepseek_reasoning_effort,
            openai_base_url=os.getenv('OPENAI_BASE_URL') or cls.openai_base_url,
            openai_model=os.getenv('OPENAI_MODEL') or cls.openai_model,
            openai_reasoning_effort=os.getenv('OPENAI_REASONING_EFFORT') or cls.openai_reasoning_effort,
            openai_proxy=os.getenv('OPENAI_PROXY_URL') or os.getenv('CODEX_PROXY_URL', ''),
            timeout=timeout,
        )


@dataclass(frozen=True)
class Result:
    provider: str
    answer: str = ''
    reason: str = ''
    error: str | None = None


def parse_answer(content):
    if not isinstance(content, str):
        raise ValueError('模型没有返回有效答案文本')
    content = content.strip()
    fenced = re.fullmatch(r'```(?:json)?\s*(.*?)\s*```', content, re.DOTALL)
    if fenced:
        content = fenced.group(1)
    try:
        data = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError('模型返回的答案不是有效 JSON') from error
    if not isinstance(data, dict) or any(
        not isinstance(data.get(field), str) or not data[field].strip()
        for field in ('answer', 'reason')
    ):
        raise ValueError('模型返回的答案或理由为空，或格式错误')
    return {field: data[field].strip() for field in ('answer', 'reason')}


def image_data_url(path):
    """Read one bounded local PNG/JPEG; do not persist or include its path in results."""
    try:
        with Path(path).open('rb') as source:
            data = source.read(MAX_IMAGE_BYTES + 1)
    except OSError as error:
        raise ValueError('无法读取图片，请重新选择 PNG 或 JPEG 图片') from error
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError('图片不能超过 10 MiB')
    try:
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            mime = 'image/png'
            offset = 8
            width = height = 0
            seen_data = ended = False
            while offset + 12 <= len(data):
                size = struct.unpack_from('>I', data, offset)[0]
                kind = data[offset + 4:offset + 8]
                end = offset + 12 + size
                if end > len(data):
                    raise ValueError
                payload = data[offset + 8:end - 4]
                if zlib.crc32(kind + payload) != struct.unpack_from('>I', data, end - 4)[0]:
                    raise ValueError
                if offset == 8:
                    if kind != b'IHDR' or size != 13:
                        raise ValueError
                    width, height = struct.unpack_from('>II', payload)
                if kind == b'IDAT':
                    seen_data = True
                if kind == b'IEND':
                    ended = size == 0 and end == len(data)
                    break
                offset = end
            if not ended or not seen_data:
                raise ValueError
        elif data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9'):
            mime = 'image/jpeg'
            offset = 2
            width = height = 0
            while offset < len(data):
                if data[offset] != 0xff:
                    raise ValueError
                while data[offset] == 0xff:
                    offset += 1
                marker = data[offset]
                offset += 1
                if marker == 0xda:
                    break
                if marker in (0x01, 0xd8, 0xd9) or 0xd0 <= marker <= 0xd7:
                    continue
                size = struct.unpack_from('>H', data, offset)[0]
                if size < 2 or offset + size > len(data):
                    raise ValueError
                if marker in (0xc0, 0xc1, 0xc2):
                    if size < 8:
                        raise ValueError
                    height, width = struct.unpack_from('>HH', data, offset + 3)
                offset += size
        else:
            raise ValueError
        if not (0 < width <= MAX_IMAGE_SIDE and 0 < height <= MAX_IMAGE_SIDE):
            raise ValueError
    except (ValueError, IndexError, struct.error) as error:
        raise ValueError('图片无效、已损坏或边长超过 8192 像素；请选择完整 PNG/JPEG 图片') from error
    return 'data:' + mime + ';base64,' + base64.b64encode(data).decode('ascii')


def call_api(provider, question, settings, image_url=None):
    if provider == 'GPT':
        key, base, model = settings.openai_key, settings.openai_base_url, settings.openai_model
        missing_key = '请在本机配置窗口保存 OpenAI API 密钥，或设置 OPENAI_API_KEY'
        extra = {}
        effort = settings.openai_reasoning_effort
        allowed = ('low','medium','high','xhigh','max')
    elif provider == 'Qwen':
        key, base, model = settings.qwen_key, settings.qwen_base_url, settings.qwen_model
        missing_key = '请设置 QWEN_API_KEY 或 DASHSCOPE_API_KEY'
        effort = settings.qwen_reasoning_effort
        allowed = ('off','low','medium','xhigh')
        extra = {'enable_thinking': effort!='off', 'max_tokens': 1200 if effort=='off' else 16384}
    elif provider == 'DeepSeek':
        key, base, model = settings.deepseek_key, settings.deepseek_base_url, settings.deepseek_model
        missing_key = '请设置 DEEPSEEK_API_KEY'
        effort = settings.deepseek_reasoning_effort
        allowed = ('off','low','high','max')
        extra = {'thinking': {'type': 'disabled' if effort=='off' else 'enabled'},
                 'max_tokens': 1200 if effort=='off' else 16384}
    else:
        raise ValueError('未知 API 提供方')
    if effort not in allowed:
        raise ValueError(f'{provider} 思考档位无效，请重新选择')
    if provider!='GPT' and effort!='off':
        extra['reasoning_effort'] = effort
    if not key.strip():
        raise ValueError(missing_key)
    body = {
        'model': model,
        'messages': [{'role': 'system', 'content': INSTRUCTIONS},
                     {'role': 'user', 'content': ([{'type': 'text', 'text': question},
                         {'type': 'image_url', 'image_url': {'url': image_url}}] if image_url else question)}],
        'response_format': {'type': 'json_object'},
        'stream': False,
        **extra,
    }
    endpoint = '/chat/completions'
    headers = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}
    if provider == 'GPT':
        endpoint = '/responses'
        body = {
            'model': model, 'instructions': INSTRUCTIONS,
            'input': [{'role': 'user', 'content': ([{'type': 'input_text', 'text': question},
                {'type': 'input_image', 'image_url': image_url}] if image_url else question)}],
            'reasoning': {'effort': settings.openai_reasoning_effort},
            'max_output_tokens': 8192 if effort in ('low','medium') else 16384, 'store': False, 'stream': False,
            'text': {'format': {'type': 'json_schema', 'name': 'competition_answer',
                                'strict': True, 'schema': ANSWER_SCHEMA}},
        }
        # This gateway documents the following UA for external Responses clients.
        if urllib.parse.urlsplit(base).hostname in ('www.micuapi.ai', 'api-slb.micuapi.ai'):
            headers['User-Agent'] = 'codex_cli_rs/0.77.0 (Windows 10.0.26100; x86_64) WindowsTerminal'
    request = urllib.request.Request(
        base.rstrip('/') + endpoint,
        data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    # Only this GPT request uses the UI proxy; never mutate process-wide proxy settings.
    open_request = urllib.request.urlopen
    if provider == 'GPT' and settings.openai_proxy:
        open_request = urllib.request.build_opener(urllib.request.ProxyHandler({
            'http': settings.openai_proxy, 'https': settings.openai_proxy})).open
    try:
        with open_request(request, timeout=settings.timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        # 不回显服务端正文，避免其中的认证信息泄露到终端。
        try:
            detail = json.loads(error.read()).get('error', {})
        except (ValueError, AttributeError):
            detail = {}
        if isinstance(detail, dict) and detail.get('code') == 'Arrearage':
            raise RuntimeError(f'{provider} API 返回 HTTP {error.code}：账户欠费或余额不足（Arrearage），请充值后重试') from error
        if provider == 'GPT' and isinstance(detail, dict) and detail.get('code') == 'insufficient_quota':
            raise RuntimeError('GPT API 额度不足，请检查 OpenAI API 余额和用量限制') from error
        raise RuntimeError(f'{provider} API 返回 HTTP {error.code}，请检查密钥、模型及端点') from error
    except (TimeoutError, urllib.error.URLError) as error:
        raise RuntimeError(f'{provider} API 网络连接失败或请求超时') from error
    try:
        if provider == 'GPT':
            if data.get('status') == 'incomplete':
                raise ValueError('模型答案未完整返回，请检查输出长度限制')
            if data.get('status') != 'completed':
                raise ValueError('GPT API 未成功完成请求')
            content = ''.join(
                part['text'] for item in data['output'] if item.get('type') == 'message'
                for part in item['content'] if part.get('type') == 'output_text')
        else:
            choice = data['choices'][0]
            if choice.get('finish_reason') == 'length':
                raise ValueError('模型答案超出长度限制，未完整返回')
            content = choice['message']['content']
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise ValueError('API 响应中没有有效答案') from error
    return parse_answer(content)


def answer_question(question, settings=None, on_result=None, image=None):
    image_url = image_data_url(image) if image is not None else None
    question = question.strip()
    if not question and image_url:
        question = IMAGE_PROMPT
    if not question:
        raise ValueError('题目不能为空')
    settings = settings or Settings.from_env()
    if not math.isfinite(settings.timeout) or settings.timeout <= 0:
        raise ValueError('超时时间必须是有限的正数')

    def invoke(provider):
        try:
            data = (call_api(provider, question, settings, image_url=image_url) if image_url
                    else call_api(provider, question, settings))
            return Result(provider, data['answer'], data['reason'])
        except Exception as error:
            message = str(error)
            for key in (settings.openai_key, settings.qwen_key, settings.deepseek_key):
                if key:
                    message = message.replace(key, '[已隐藏]')
            return Result(provider, error=message or type(error).__name__)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(invoke, provider) for provider in PROVIDERS]
        completed = {}
        for future in as_completed(futures):
            result = future.result()
            completed[result.provider] = result
            if on_result is not None:
                on_result(result)
        return [completed[provider] for provider in PROVIDERS]


def normalize_answer(answer, choices=False):
    normalized = unicodedata.normalize('NFKC', answer).strip()
    compact = re.sub(r'[\s,，、;/|+]+', '', normalized).upper()
    if choices and re.fullmatch(r'[A-H]+', compact):
        return ''.join(sorted(set(compact)))
    normalized = re.sub(r'\s+', '', normalized).casefold()
    if normalized in ('正确', '对', 'true'):
        return '正确'
    if normalized in ('错误', '错', 'false'):
        return '错误'
    return normalized


def compare_answers(results, question=''):
    if len(results) != 3 or any(result.error or not result.answer.strip() for result in results):
        return '三个模型答案是否一致：无法完整比较（有模型调用失败或未返回答案）。'
    question = unicodedata.normalize('NFKC', question)
    option_labels = set(re.findall(r'(?:^|\s|[（(])([A-H])[.、:：)）]', question))
    choices = bool(re.search(r'选择题|单选|多选', question)) or len(option_labels) >= 2
    if len({normalize_answer(result.answer, choices) for result in results}) == 1:
        return '三个模型答案是否一致：一致。'
    detail = '；'.join(f'{result.provider}：{result.answer}' for result in results)
    return ('三个模型答案是否一致：不一致。\n' + detail
            + '\n按答案文本比较；简答题的同义表述可能被判为不一致。')


def format_output(question, results):
    sections = ['题目：\n' + question]
    for result in results:
        answer = result.answer if not result.error else '调用失败'
        reason = result.reason if not result.error else result.error
        sections.append(f'======== {result.provider} ========\n答案：{answer}\n理由：{reason}')
    sections.append('======== 综合分析 ========\n' + compare_answers(results, question))
    return '\n\n'.join(sections)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='GPT / Qwen / DeepSeek 固定并行答题')
    parser.add_argument('question', nargs='?', help='题目及选项')
    parser.add_argument('--file', type=Path, help='读取 UTF-8 文本题目')
    parser.add_argument('--image', type=Path, help='附加一张 PNG/JPEG 题目图片（最大 10 MiB，边长最多 8192）')
    parser.add_argument('--timeout', type=float, default=120, help='每路请求超时秒数（默认 120）')
    output_mode = parser.add_mutually_exclusive_group()
    output_mode.add_argument('--json', action='store_true', help='输出完整结构化结果')
    output_mode.add_argument('--json-lines', action='store_true', help='每个模型完成后立即输出结果事件')
    args = parser.parse_args(argv)
    if args.question is not None and args.file:
        parser.error('题目参数和 --file 只能使用一个')
    try:
        if args.file:
            question = args.file.read_text(encoding='utf-8-sig')
        elif args.question is not None:
            question = args.question
        elif args.image:
            question = ''
        elif not sys.stdin.isatty():
            question = sys.stdin.read()
        else:
            print('输入题目及选项，空行结束：', flush=True)
            lines = []
            while True:
                line = input()
                if not line.strip():
                    break
                lines.append(line)
            question = '\n'.join(lines)
        if args.image and not question.strip():
            question = IMAGE_PROMPT
        image_args = {'image': args.image} if args.image else {}
        if args.json_lines:
            def publish(result):
                print(json.dumps({'type': 'model_result', 'result': asdict(result)},
                                 ensure_ascii=False), flush=True)
            results = answer_question(question, Settings.from_env(args.timeout), on_result=publish, **image_args)
        else:
            results = answer_question(question, Settings.from_env(args.timeout), **image_args)
    except (ValueError, OSError, EOFError) as error:
        print(f'输入错误：{error}', file=sys.stderr)
        return 2
    if args.json or args.json_lines:
        payload = {'question': question.strip(), 'models': [asdict(result) for result in results],
                   'analysis': compare_answers(results, question)}
        if args.json_lines:
            payload['type'] = 'complete'
        print(json.dumps(payload, ensure_ascii=False), flush=True)
    else:
        print(format_output(question.strip(), results))
    return 1 if any(result.error for result in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
