"""Small dependency-free terminal workbench, with slash commands and live status."""
from decimal import Decimal
import getpass
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import threading
import time
import unicodedata

from .builds import build_status, create_build, execute_build, load_build
from .errors import PipelineError, ConfigError
from .settings import Settings
from .util import canonical


def visible(value):
    return ''.join(c if not unicodedata.category(c).startswith('C') else ' ' for c in str(value))


def fit(text, width):
    result, length = '', 0
    for c in visible(text):
        size = 0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1
        if length + size > width - 1:
            return result + '…'
        result += c
        length += size
    return result


def cell_width(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in visible(text))


class Console:
    def __init__(self, output=None, *, plain=False):
        self.output = output or sys.stdout
        self.color = not plain and self.output.isatty() and not os.environ.get('NO_COLOR')
        self.lock = threading.RLock()

    def paint(self, text, code='36'):
        return '\033[' + code + 'm' + text + '\033[0m' if self.color else text

    def line(self, text=''):
        with self.lock:
            if self.color:
                self.output.write('\r\033[2K')
            self.output.write(str(text) + '\n')
            self.output.flush()

    def panel(self, title, lines):
        width = max(22, min(108, shutil.get_terminal_size((100, 24)).columns - 4))
        label = fit(' ' + title + ' ', width - 1)
        self.line(self.paint('╭' + label + '─' * max(0, width - cell_width(label)) + '╮'))
        for text in lines:
            text = fit(text, width - 2)
            self.line(self.paint('│ ', '36') + text + ' ' * max(0, width - 1 - cell_width(text)) + self.paint('│'))
        self.line(self.paint('╰' + '─' * width + '╯'))


class Progress:
    def __init__(self, console, root, *, synthetic=False):
        self.console, self.root, self.synthetic = console, Path(root), synthetic
        self.stop = threading.Event()
        self.thread = None
        self.started = time.monotonic()
        self.current, self.done, self.passed, self.cost = '准备媒体 / 预清理', 0, 0, Decimal(0)
        self.log = None

    def __enter__(self):
        fd = os.open(self.root / 'terminal.events.jsonl', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        self.log = os.fdopen(fd, 'a', encoding='utf-8')
        if self.console.color:
            self.thread = threading.Thread(target=self.animate, daemon=True)
            self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=1)
        self.log.close()
        self.console.line()

    def animate(self):
        index = 0
        while not self.stop.wait(0.15):
            with self.console.lock:
                label = '模拟' if self.synthetic else '运行'
                text = f'{"⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[index % 10]} {label} · {self.current} · 完成API {self.done} · QA通过 {self.passed} · ¥{self.cost:.5f} · {int(time.monotonic()-self.started)}s'
                self.console.output.write('\r\033[2K' + self.console.paint(fit(text, shutil.get_terminal_size((100, 24)).columns - 2)))
                self.console.output.flush()
            index += 1

    def observe(self, event):
        self.log.write(canonical(event) + '\n')
        self.log.flush()
        if event['kind'] == 'snapshot':
            self.done, self.passed, self.cost = event['done'], event['passed'], Decimal(event['cost'])
        elif event['kind'] == 'api_wait':
            self.current = f'{event["role"]} / {event["model"]} / {event["unit_id"]}（准备媒体）'
        elif event['kind'] == 'request_start':
            self.current = f'{event["role"]} / 视频 {event["video_id"][:8]}（推理中）'
        elif event['kind'] == 'request_done':
            self.done += 1
            self.cost += Decimal(event['cost'])
            if not self.console.color:
                self.console.line(f'  API {event["role"]} 完成 · in={event["input_tokens"]} out={event["output_tokens"]} · ¥{event["cost"]}')
        elif event['kind'] == 'stage':
            if event['stage'] == 'retention' and event['decision'] == 'pass':
                self.passed += 1
            if event['stage'] == 'execution' and event['decision'] == 'pending':
                self.console.line(self.console.paint('  × 未完成 · ' + event['video_id'][:8] + ' · ' + visible(event['reason'])
                                  + ' · ' + visible(canonical(event.get('detail', {}))), '31'))
            elif event['stage'] in ('prepare', 'caption_gate', 'branch', 'retention', 'execution') and event['decision'] != 'pending':
                mark = '✓' if event['decision'] == 'pass' else '×'
                self.console.line(f'  {mark} {event["stage"]} · {event["video_id"][:8]} · {visible(event["reason"])}')
        elif event['kind'] in ('response_normalized', 'cache_reused'):
            self.console.line('  ' + event['role'] + ' · ' + ('保留原响应，合并重复uncertain_details' if event['kind'] == 'response_normalized' else '复用已付费响应，无新API调用'))


HELP = [
    '/new [名称]       新建 s_YYYYMMDD_HHMM 轮次（不立即调用模型）',
    '/run [阶段]       执行当前轮次；阶段 all / prepare / caption',
    '/resume [目录]    选择已有轮次；/run 继续执行',
    '/recover 旧目录 名称   新建恢复轮次，复用已付费caption响应；不立即调用API',
    '/source 地址      持久保存MP4目录、文件或直链',
    '/output 目录      持久保存构建输出父目录',
    '/models           查看模型；/model 名称或序号 选择默认模型',
    '/model set 名称 字段 值   修改base_url、model、transport等',
    '/route video|text|C_GATE|all 模型|active   设置阶段路由',
    '/config           查看脱敏配置；/config edit 打开本机编辑器',
    '/key [模型]       隐藏输入并一次保存Key，也可直接编辑配置',
    '/set recipe.l2_fps 2      修改配方；limits.max_cost_cny等同理',
    '/recipe benchmark_v1      启用General/Long/Knowledge能力配方；仅新轮次',
    '/models ping [模型]      仅GET /models，不做付费推理',
    '/status /report   当前轮次状态和报告位置',
    '/demo [名称]      完整离线模拟（无需源视频或API Key）',
    '/help /quit       帮助 / 退出；运行中Ctrl+C中断并保留账本',
]


class Workbench:
    def __init__(self, settings=None, *, console=None, input_fn=None):
        self.settings = settings or Settings()
        self.console = console or Console()
        self.input = input_fn or input
        self.current = None
        self.running = True
        self.failed_builds = set()
        self.last_exit_code = 0

    def dashboard(self):
        data = self.settings.redacted()
        self.console.panel('Video SFT Builder · 0.2', [
            'MP4 → 三级caption → 能力任务QA → 自动审核候选',
            'QA配方: '+data['recipe'].get('qa_recipe','legacy_v1')+' · /recipe benchmark_v1 启用三分支能力配方（仅新轮次）',
            '来源: ' + (data['source'] or '未设置；/source 或 /new 时填写'),
            '输出: ' + (data['output_dir'] or '未设置；/output 或 /new 时填写'),
            f'模型: {data["active_model"]}  · 最多视频 {data["limits"]["max_videos"]}  · 本轮预算 ¥{data["limits"]["max_cost_cny"]}',
            '当前: ' + (self.current.name if self.current else '尚未选择轮次'),
            '配置: ' + str(self.settings.path),
        ])
        self.console.line('  /new 新建  /run 执行  /models 模型  /config 配置  /help 帮助  /quit 退出')

    def ask_path(self, key, prompt):
        if not self.settings.data[key]:
            value = self.input(prompt).strip()
            if not value:
                raise ConfigError('Required path/address was left empty')
            self.settings.data[key] = value
            self.settings.save()

    def model_name(self, value):
        names = list(self.settings.data['models'])
        if value.isdigit() and 1 <= int(value) <= len(names):
            return names[int(value) - 1]
        if value not in names:
            raise ConfigError('Unknown model profile; use /models to list configured names')
        return value

    def run_build(self, through):
        if self.current is None:
            raise ConfigError('Create /new or select /resume a build first')
        self.failed_builds.add(str(self.current))
        _, manifest, config = load_build(self.current)
        lines = [
            '阶段: ' + through + (' · 离线模拟，无实际费用' if manifest['synthetic'] else ' · 将按冻结配置调用模型API'),
            '来源: ' + manifest['source']['public_source'],
            '结果: ' + str(self.current),
        ]
        lines += [role + ' → ' + config.provider_id(role) + ' / ' + config.provider_settings(role)['model']
                  for role in ('A1', 'A2', 'C_GATE', 'A3', 'A5', 'A7')]
        lines += [
            'FPS: ' + ' / '.join(role + '=' + str(config.profile(role)['fps']) for role in ('A1', 'A2', 'A7')),
            f'视频上限 {config.data["run"]["max_videos"]} · 金额上限 ¥{config.data["budgets"]["max_cost"]} · 通过全保留 / 拒绝不补题',
        ]
        from .abilities import branches,branch_plan,benchmark_recipe
        for branch in branches(config):
            p=branch_plan(config,branch)
            lines.append(f'{branch}: 适配{p["fit"]}＋均衡{p["balance"]}候选；均衡尝试≤{p["attempts"]}；文本角色{p["role"]}')
        if benchmark_recipe(config):
            lines.append('无弃答时：文本生成11次＋逐题A7最多13次；另计共享caption/C_GATE。Knowledge与General共用A3。')
        self.console.panel('执行预览 · ' + config.run_id, lines)
        with Progress(self.console, self.current, synthetic=manifest['synthetic']) as progress:
            value = execute_build(self.current, through=through, observer=progress.observe)
        if value['status'] == 'complete':
            self.failed_builds.discard(str(self.current))
        lines = [
            '状态: ' + value['status'] + f' · 自动通过 {value["auto_passed"]} · pending {value["pending_entities"]}',
            '候选: ' + value['export'], '报告: ' + value['report'],
            '当前输出为自动审核候选，尚未GLM processor验收；cot=null。']
        if value['status'] != 'complete':
            lines.append('部分产物已保留；本轮未完成，退出终端时返回非零退出码。')
            for row in value['completion'].get('videos', []):
                lines.append(f'{row["video_id"][:8]} · L1 {row["l1_completed"]}/{row["l1_expected"]} · L2 {row["l2_completed"]}/{row["l2_expected"]} · 完整L3 {row["l3_complete"]}')
                stop = row.get('stop', {})
                if stop:
                    lines.append('停止位置: ' + str(stop.get('role', stop.get('stage'))) + ' / ' + str(stop.get('unit_id', 'preflight')))
            lines += [visible(canonical(item)) for item in value['completion']['failures']]
        self.console.panel('本阶段完成' if value['status'] == 'complete' else '未完成 · 检查失败原因与覆盖缺口', lines)

    def dispatch(self, line):
        words = shlex.split(line)
        if not words:
            return
        aliases = {'1': '/new', '2': '/resume', '3': '/models', '4': '/config', '5': '/status', '0': '/quit'}
        command, args = aliases.get(words[0], words[0]), words[1:]
        if command in ('/quit', '/exit', 'quit', 'exit'):
            self.running = False
        elif command in ('/help', '?'):
            for text in HELP:
                self.console.line('  ' + text)
        elif command in ('/source', '/output'):
            key = 'source' if command == '/source' else 'output_dir'
            value = ' '.join(args) if args else self.input('来源地址: ' if key == 'source' else '输出父目录: ').strip()
            if not value:
                raise ConfigError('Address may not be empty')
            if key == 'output_dir' and not Path(value).expanduser().is_absolute():
                raise ConfigError('Output directory must be absolute')
            self.settings.data[key] = value
            self.settings.save()
            self.console.line('已保存；仅影响之后新建的轮次。')
        elif command in ('/new', '/demo'):
            if len(args) > 1:
                raise ConfigError('Use one build name without spaces; nothing is silently truncated')
            synthetic = command == '/demo'
            self.ask_path('output_dir', '输出父目录（保存一次）: ')
            if not synthetic:
                self.ask_path('source', 'MP4来源目录 / 文件 / 直链（保存一次）: ')
            name = args[0] if args else self.input('本次名称 s: ').strip()
            self.current = create_build(self.settings, name, synthetic=synthetic)
            self.console.line('已创建: ' + str(self.current))
            if synthetic:
                self.run_build('all')
            else:
                self.console.line('输入 /run 开始；也可 /run prepare 或 /run caption。')
        elif command == '/run':
            self.run_build(args[0] if args else 'all')
        elif command == '/resume':
            value = ' '.join(args) if args else self.input('已有轮次目录或名称: ').strip()
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = Path(self.settings.data['output_dir']).expanduser() / path
            self.current, _, _ = load_build(path)
            self.console.line('已选择: ' + str(self.current) + '；输入 /run 继续，不会新建目录。')
        elif command in ('/status', '/report'):
            if not self.current:
                raise ConfigError('No selected build')
            self.console.line(json.dumps(build_status(self.current), ensure_ascii=False, indent=2))
        elif command == '/models' and args and args[0] == 'ping':
            name = self.model_name(args[1]) if len(args) > 1 else self.settings.data['active_model']
            self.ping(name)
        elif command == '/models':
            for i, name in enumerate(self.settings.data['models'], 1):
                p = self.settings.provider(name)
                capabilities = ','.join(k for k, v in p['capabilities'].items() if v)
                mark = '●' if name == self.settings.data['active_model'] else '○'
                has_key = bool(self.settings.data['models'][name].get('api_key') or os.environ.get(p['key_env']))
                key_status = '已配置' if has_key else '未配置（必需）' if p['auth_required'] else '免鉴权/未配置'
                sampling = ' · 采样待确认' if p['capabilities']['native_video'] and not p['sampling_verified'] else ''
                self.console.line(f'  {mark} {i}. {name} · model={visible(p["model"])} · {capabilities} · Key={key_status}{sampling}')
            self.console.line('选择: /model 名称或序号；按阶段配置: /route video|text|C_GATE 模型')
        elif command == '/model' and args and args[0] == 'set':
            if len(args) < 4:
                raise ConfigError('Usage: /model set PROFILE FIELD VALUE')
            name = self.model_name(args[1])
            if args[2] == 'api_key':
                raise ConfigError('Use /key for hidden input, or /config edit; keys are never slash-command arguments')
            self.assign(self.settings.data['models'][name], args[2], ' '.join(args[3:]))
            self.settings.save()
            self.console.line('模型配置已保存。')
        elif command == '/model':
            value = args[0] if args else self.input('模型名称或序号（/models可查看）: ').strip()
            self.settings.data['active_model'] = self.model_name(value)
            self.settings.save()
            self.console.line('默认模型已保存；已有轮次保持原路由。')
            if self.settings.data['routes']:
                self.console.line('仍有阶段固定覆盖；/route查看，/route all active清除。')
        elif command == '/route':
            if not args:
                self.console.panel('之后新轮次的API路由', [role + ' → ' + profile + ' / ' + self.settings.provider(profile)['model']
                    for role, profile in self.settings.routes().items()])
                return
            if len(args) != 2:
                raise ConfigError('Usage: /route video|text|C_GATE|all|ROLE PROFILE|active')
            groups = {'video': ('A1', 'A2', 'A7'), 'text': ('A3', 'A5'), 'all': ('A1', 'A2', 'C_GATE', 'A3', 'A5', 'A7')}
            roles = groups.get(args[0], (args[0],))
            for role in roles:
                if args[1] == 'active':
                    self.settings.data['routes'].pop(role, None)
                else:
                    self.settings.data['routes'][role] = self.model_name(args[1])
            self.settings.save()
            self.console.line('API路由已保存；之后新建的轮次使用此路由。')
        elif command == '/recover':
            if len(args) != 2:
                raise ConfigError('Usage: /recover OLD_BUILD_DIR NEW_NAME')
            from .recovery import recover_build
            self.current = recover_build(args[0], args[1])
            self.console.line('恢复轮次已创建（尚未调用API）: ' + str(self.current))
            self.console.line('历史费用已纳入预算；/run all继续，旧轮次保留。')
        elif command == '/key':
            name = self.model_name(args[0]) if args else self.settings.data['active_model']
            if not sys.stdin.isatty():
                raise ConfigError('Hidden key input needs an interactive terminal; edit the private config instead')
            self.settings.data['models'][name]['api_key'] = getpass.getpass('API Key（不回显，保存一次）: ').strip()
            self.settings.save()
            self.console.line('Key已保存到私有配置；不会写入构建目录。')
        elif command == '/config' and args and args[0] == 'edit':
            editor = os.environ.get('VISUAL') or os.environ.get('EDITOR') or shutil.which('nano') or shutil.which('vi')
            if not editor:
                raise ConfigError('No editor found; edit this private file manually: ' + str(self.settings.path))
            subprocess.run(shlex.split(editor) + [str(self.settings.path)], check=True)
            self.settings.reload()
            self.console.line('配置已重新加载；已有轮次保持冻结参数。')
        elif command == '/config':
            self.settings.reload()
            self.console.line('私有配置: ' + str(self.settings.path))
            self.console.line(json.dumps(self.settings.redacted(), ensure_ascii=False, indent=2))
        elif command == '/set':
            if len(args) < 2 or args[0].split('.')[0] not in ('recipe', 'limits', 'download'):
                raise ConfigError('Usage: /set recipe.FIELD|limits.FIELD|download.FIELD VALUE')
            self.assign(self.settings.data, args[0], ' '.join(args[1:]))
            self.settings.save()
            self.console.line('已保存；之后新建的轮次生效。')
        elif command == '/recipe':
            if not args:
                self.console.line('当前新轮次配方: '+self.settings.data['recipe'].get('qa_recipe','legacy_v1'))
                self.console.line('/recipe benchmark_v1：General2+3 / Long1+2 / Knowledge2+3；/recipe legacy_v1：旧两分支。')
                return
            if len(args)!=1:
                raise ConfigError('Usage: /recipe benchmark_v1|legacy_v1')
            self.settings.select_recipe(args[0])
            self.console.line('配方已保存，只影响之后/new的轮次；已有冻结轮次不改变。')
        elif command == '/reload':
            self.settings.reload()
            self.dashboard()
        else:
            raise ConfigError('Unknown command; /help lists available operations')

    @staticmethod
    def assign(mapping, path, value):
        from .util import strict_json
        parts = path.split('.')
        for part in parts[:-1]:
            mapping = mapping.setdefault(part, {})
            if not isinstance(mapping, dict):
                raise ConfigError('Cannot edit a child of a scalar value')
        try:
            parsed = strict_json(value)
        except ValueError:
            parsed = value
        mapping[parts[-1]] = parsed

    def ping(self, name):
        # GET-only connectivity and served-model lookup, never inference.
        from .provider import http_json
        p = self.settings.provider(name)
        key = self.settings.data['models'][name].get('api_key') or os.environ.get(p['key_env'])
        if not key and p['auth_required']:
            raise ConfigError('Configure this model API key once before connectivity checks')
        headers = {'Accept': 'application/json'}
        if key:
            headers['Authorization'] = 'Bearer ' + key
        value = http_json(p['base_url'].rstrip('/') + '/models', headers=headers, timeout=15, limit=1000000)
        found = any(item.get('id') == p['model'] for item in value.get('data', []))
        self.console.line(f'连接成功；模型列表包含当前model ID: {found}。仅GET检查，不验证视频能力。')

    def loop(self):
        self.dashboard()
        try:
            import readline
            commands = [line.split()[0] for line in HELP]
            readline.set_completer(lambda text, n: [c for c in commands if c.startswith(text)][n] if n < len([c for c in commands if c.startswith(text)]) else None)
            readline.parse_and_bind('tab: complete')
        except ImportError:
            pass
        while self.running:
            try:
                line = self.input(self.console.paint('❯ ', '35'))
                self.dispatch(line)
            except EOFError:
                break
            except KeyboardInterrupt:
                self.last_exit_code = 130
                self.console.line('已中断；中间产物和请求账本保留。已发送的未决请求不会自动重发。')
            except (PipelineError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                self.console.line(self.console.paint('× ' + visible(str(error)), '31'))
                try:
                    self.settings.reload()
                except PipelineError:
                    self.console.line('私有配置有误，请手动修正该文件后输入 /reload。')
        self.console.line('已退出。构建文件已保留。')
        return self.last_exit_code or (2 if self.failed_builds else 0)


def launch(path=None, *, plain=False):
    return Workbench(Settings(path), console=Console(plain=plain)).loop()
