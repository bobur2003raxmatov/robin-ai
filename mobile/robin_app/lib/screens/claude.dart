import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';

import '../api.dart';

/// 🤖 Claude (admin): same Claude Code as Admin → Claude in the dashboard. Works only while the icon is lit.
class ClaudeScreen extends StatefulWidget {
  const ClaudeScreen({super.key});
  @override
  State<ClaudeScreen> createState() => _ClaudeScreenState();
}

class _ClaudeScreenState extends State<ClaudeScreen> {
  Map st = {};
  final log = <Map<String, dynamic>>[];
  final input = TextEditingController();
  final scroll = ScrollController();
  bool running = false;
  String hint = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final s = await Api.I.get('/api/claude/status');
      if (!mounted) return;
      setState(() {
        st = s;
        running = s['running'] == true;
        log
          ..clear()
          ..addAll([
            for (final h
                in (s['history'] as List? ?? []).reversed
                    .take(15)
                    .toList()
                    .reversed) ...[
              {'t': 'q', 'text': h['prompt']},
              {'t': 'text', 'text': h['result']},
            ],
          ]);
      });
      _down();
    } catch (e) {
      if (mounted) setState(() => hint = '$e');
    }
  }

  void _down() => WidgetsBinding.instance.addPostFrameCallback((_) {
    if (scroll.hasClients) scroll.jumpTo(scroll.position.maxScrollExtent);
  });

  Future<void> _toggle() async {
    try {
      final s = await Api.I.post('/api/claude/toggle', {
        'enabled': st['enabled'] != true,
      });
      setState(() => st = s);
    } catch (e) {
      setState(() => hint = '$e');
    }
  }

  Future<void> _send() async {
    final t = input.text.trim();
    if (t.isEmpty || running) return;
    input.clear();
    setState(() {
      running = true;
      hint = '⏳ Claude ishlayapti…';
      log.add({'t': 'q', 'text': t});
    });
    _down();
    await for (final ev in Api.I.claudeStream(t)) {
      if (!mounted) return;
      setState(() {
        if (ev['t'] == 'tool') hint = '⚙️ ${ev['name']}: ${ev['input']}';
        if (ev['t'] != 'done' && ev['t'] != 'stderr') log.add(ev);
      });
      _down();
    }
    if (mounted)
      setState(() {
        running = false;
        hint = '✅ Tayyor';
      });
  }

  Widget _item(Map ev, ColorScheme cs) {
    switch (ev['t']) {
      case 'q':
        return Padding(
          padding: const EdgeInsets.only(top: 12, bottom: 4),
          child: Text(
            '🧑 ${ev['text']}',
            style: const TextStyle(
              color: Color(0xFF9FE6C4),
              fontWeight: FontWeight.w600,
            ),
          ),
        );
      case 'text':
        return MarkdownBody(
          data: '${ev['text']}',
          styleSheet: MarkdownStyleSheet(
            p: const TextStyle(color: Color(0xFFDFE6FF)),
            code: const TextStyle(
              color: Color(0xFFFFD58A),
              backgroundColor: Color(0x22FFFFFF),
            ),
          ),
        );
      case 'tool':
        return Text(
          '⚙️ ${ev['name']}  ${ev['input']}',
          style: const TextStyle(
            color: Color(0xFF8AB4FF),
            fontFamily: 'monospace',
            fontSize: 12,
          ),
        );
      case 'tool_result':
        return Text(
          '${ev['is_error'] == true ? '❌' : '↳'} ${'${ev['text']}'.split('\n').first}',
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(color: Color(0xFF8D98B8), fontSize: 12),
        );
      case 'result':
        return Text(
          '${ev['is_error'] == true ? '❌' : '✅'} ${ev['turns']} qadam · \$${(ev['cost'] ?? 0).toStringAsFixed(4)}',
          style: const TextStyle(color: Color(0xFF8D98B8), fontSize: 12),
        );
      case 'error':
        return Text(
          '⚠️ ${ev['text']}',
          style: const TextStyle(color: Color(0xFFFF8A8A)),
        );
      default:
        return Text(
          '${ev['text'] ?? ''}',
          style: const TextStyle(color: Color(0xFF8D98B8), fontSize: 12),
        );
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final on = st['enabled'] == true;
    return Column(
      children: [
        ListTile(
          leading: GestureDetector(
            onTap: _toggle,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 250),
              width: 48,
              height: 48,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                border: Border.all(
                  color: on ? Colors.green : cs.outlineVariant,
                  width: 2,
                ),
                boxShadow: on
                    ? [
                        BoxShadow(
                          color: Colors.green.withValues(alpha: .5),
                          blurRadius: 14,
                        ),
                      ]
                    : null,
              ),
              child: Opacity(
                opacity: on ? 1 : .4,
                child: const Text('🤖', style: TextStyle(fontSize: 26)),
              ),
            ),
          ),
          title: const Text(
            'Claude Code',
            style: TextStyle(fontWeight: FontWeight.w800),
          ),
          subtitle: Text(
            on
                ? '🟢 yoqilgan · ${st['permission_mode'] ?? ''}'
                : "⚫ o'chiq — yoqish uchun 🤖 ni bosing",
          ),
          trailing: IconButton(
            tooltip: 'STOP',
            icon: Icon(Icons.stop_circle, color: cs.error),
            onPressed: () => Api.I
                .post('/api/claude/stop')
                .then((_) => _load())
                .catchError((_) {}),
          ),
        ),
        Expanded(
          child: Container(
            margin: const EdgeInsets.symmetric(horizontal: 10),
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: const Color(0xFF0B1020),
              borderRadius: BorderRadius.circular(12),
            ),
            child: log.isEmpty
                ? const Center(
                    child: Text(
                      "Hali vazifa yo'q",
                      style: TextStyle(color: Color(0xFF8D98B8)),
                    ),
                  )
                : ListView(
                    controller: scroll,
                    children: [for (final e in log) _item(e, cs)],
                  ),
          ),
        ),
        if (hint.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 6, 12, 0),
            child: Text(
              hint,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 12, color: cs.outline),
            ),
          ),
        Padding(
          padding: const EdgeInsets.all(8),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  controller: input,
                  enabled: on && !running,
                  minLines: 1,
                  maxLines: 4,
                  decoration: InputDecoration(
                    hintText: on ? "Claude'ga vazifa…" : 'Avval 🤖 ni yoqing',
                    isDense: true,
                  ),
                ),
              ),
              const SizedBox(width: 6),
              IconButton.filled(
                onPressed: on && !running ? _send : null,
                icon: running
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.play_arrow),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
