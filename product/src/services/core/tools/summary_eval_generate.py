"""P1 sample generation for summary-review-v2; never updates product settings."""

import sys, pathlib, sqlite3, json, hashlib, datetime, time, argparse
ROOT = pathlib.Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / 'product/src/services/core'))
from app.adapters.summary.openai_compatible import OpenAICompatibleSummarizer, SummarySettings, _summary_input
from app.domain.models import SummaryStrength, Chunk
from app.knowledge.chunking import estimate_tokens
from app.platforms.secrets import unprotect_secret

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='生成隔离的总结评测候选，不修改产品设置')
    parser.add_argument('version')
    parser.add_argument('label', nargs='?', choices=['通用', '简要', '详细'])
    parser.add_argument('--base', type=pathlib.Path, required=True)
    parser.add_argument('--stage', choices=['screen', 'full'], default='screen')
    parser.add_argument('--dry-run', action='store_true')
    return parser.parse_args(argv)

def main(argv=None):
    args = parse_args(argv)
    BASE = args.base.resolve()
    version = args.version
    if not version.startswith('V') or not version[1:].isdigit():
        raise ValueError('版本必须为 V 加数字')
    folder = BASE / ('Agent2_' + version)
    prompt = (folder / 'Prompt.md').read_text(encoding='utf-8-sig').strip()
    if not prompt:
        raise ValueError('候选 Prompt 不能为空')
    labels = [args.label] if args.label else ['通用'] if args.stage == 'screen' else ['通用', '简要', '详细']
    if args.dry_run:
        print(json.dumps({'version': version, 'labels': labels, 'stage': args.stage, 'production_settings_write': False}, ensure_ascii=False))
        return 0
    conn = sqlite3.connect((ROOT / 'product/local/knowledge.db').as_uri() + '?mode=ro', uri=True)
    try:
        settings = dict(conn.execute("select key,value from app_settings where key like 'summary_%'"))
    finally:
        conn.close()
    secret = settings.get('summary_api_key', '')
    if secret.startswith(('dpapi:', 'fernet:')):
        secret = unprotect_secret(secret, purpose='总结模型 API Key')
    api_settings = SummarySettings(api_url=settings['summary_api_url'], api_key=secret, model=settings['summary_model'], api_mode=settings.get('summary_api_mode'), provider=settings.get('summary_provider'), timeout_seconds=int(settings.get('summary_timeout_seconds') or 360))
    summarizer = OpenAICompatibleSummarizer(api_settings)
    text = (BASE / 'P1_产品保存原文.txt').read_text(encoding='utf-8')
    sha = lambda s: hashlib.sha256(s.encode()).hexdigest()
    chunk = Chunk(1, 0, 1607, text, sha(text), estimate_tokens(text))
    for label, strength in [('通用', SummaryStrength.STANDARD), ('简要', SummaryStrength.QUICK), ('详细', SummaryStrength.DEEP)]:
        if label not in labels:
            continue
        output = folder / (label + '版.md')
        user = _summary_input('让多个模型评审打分，用 Agent 迭代优化 T3 Code 界面 - video_trimmed', strength, (chunk,), None, style='general')
        request = summarizer._summary_payload(prompt=prompt, user_content=user)
        if output.exists():
            evidence = json.loads((folder / (label + '版_证据.json')).read_text(encoding='utf-8'))
            saved_request = json.loads((folder / (label + '版_请求.json')).read_text(encoding='utf-8'))
            if saved_request != request or evidence['api_url'] != api_settings.api_url or evidence['prompt_sha256'] != sha(prompt) or evidence['transcript_sha256'] != sha(text) or evidence['output_sha256'] != sha(output.read_text(encoding='utf-8')):
                raise ValueError('已有输出与当前候选或原文不一致；请使用新版本号')
            print(json.dumps({'version': version, 'label': label, 'state': 'already_saved'}, ensure_ascii=False), flush=True)
            continue
        (folder / (label + '版_请求.json')).write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding='utf-8')
        start = time.monotonic()
        try:
            result = summarizer.summarize_chunks((chunk,), title='让多个模型评审打分，用 Agent 迭代优化 T3 Code 界面 - video_trimmed', strength=strength, prompt=prompt, style='general')
        except Exception as exc:
            cause = exc.__cause__
            (folder / (label + '版_失败.json')).write_text(json.dumps({'type': type(exc).__name__, 'message': str(exc).replace(secret, '[REDACTED]'), 'cause_type': type(cause).__name__ if cause else None, 'cause_detail': str(cause).replace(secret, '[REDACTED]') if cause else None, 'seconds': round(time.monotonic() - start, 2), 'at': datetime.datetime.now(datetime.UTC).isoformat()}, ensure_ascii=False), encoding='utf-8')
            print(json.dumps({'version': version, 'label': label, 'state': 'failed', 'type': type(exc).__name__}, ensure_ascii=False), flush=True)
            raise SystemExit(2)
        output.write_text(result.markdown, encoding='utf-8')
        evidence = {'version': version, 'label': label, 'strength': strength.value, 'style': 'general', 'source_url': 'https://www.bilibili.com/video/BV1vF4F64EsW/?p=1', 'source_kind': 'product_saved_transcript', 'source_content_id': 'content_99cec1ccd2da4f8ca0d584efaf25cd01', 'transcript_sha256': sha(text), 'prompt_sha256': sha(prompt), 'output_sha256': sha(result.markdown), 'model': api_settings.model, 'api_url': api_settings.api_url, 'api_mode': api_settings.api_mode, 'characters': len(result.markdown), 'seconds': round(time.monotonic() - start, 2), 'created_at_utc': datetime.datetime.now(datetime.UTC).isoformat(), 'path': 'product OpenAICompatibleSummarizer.summarize_chunks; one full-source chunk; no product task or summary-version row created'}
        (folder / (label + '版_证据.json')).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'version': version, 'label': label, 'state': 'saved', 'characters': len(result.markdown), 'seconds': evidence['seconds']}, ensure_ascii=False), flush=True)
if __name__ == '__main__':
    raise SystemExit(main())
