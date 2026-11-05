import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';

import '../api.dart';

/// Approval Center: ROBIN asks before risky actions — approve / reject from the phone. Also the emergency STOP.
class ApprovalsScreen extends StatefulWidget {
  final VoidCallback onChanged;
  const ApprovalsScreen({super.key, required this.onChanged});
  @override
  State<ApprovalsScreen> createState() => _ApprovalsScreenState();
}

class _ApprovalsScreenState extends State<ApprovalsScreen> {
  List items = [];
  bool loading = true, stopped = false;
  String error = '';
  StreamSubscription? _sub;

  @override
  void initState() {
    super.initState();
    _load();
    _sub = Api.I.events.listen((m) {
      if (m['type'] == 'approval_request') _load();
    });
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final r = await Api.I.get('/api/approvals');
      if (mounted)
        setState(() {
          items = r as List;
          error = '';
          loading = false;
        });
    } catch (e) {
      if (mounted)
        setState(() {
          error = '$e';
          loading = false;
        });
    }
  }

  Future<void> _decide(String id, bool ok) async {
    try {
      await Api.I.post('/api/approvals/$id', {'approved': ok});
      widget.onChanged();
      _load();
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> _stop() async {
    try {
      await Api.I.post(
        stopped ? '/api/emergency/resume' : '/api/emergency/stop',
      );
      setState(() => stopped = !stopped);
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Color _risk(String r, ColorScheme cs) => r == 'high' || r == 'critical'
      ? cs.error
      : (r == 'medium' ? Colors.orange : cs.primary);

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final pending = items.where((a) => a['status'] == 'pending').toList();
    final done = items.where((a) => a['status'] != 'pending').take(30).toList();
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          Row(
            children: [
              const Expanded(
                child: Text(
                  'Tasdiqlar',
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
                ),
              ),
              FilledButton.icon(
                style: FilledButton.styleFrom(
                  backgroundColor: stopped ? Colors.green : cs.error,
                ),
                onPressed: _stop,
                icon: Icon(stopped ? Icons.play_arrow : Icons.stop_circle),
                label: Text(stopped ? 'Davom ettirish' : 'STOP'),
              ),
            ],
          ),
          const SizedBox(height: 8),
          if (loading)
            const Center(
              child: Padding(
                padding: EdgeInsets.all(30),
                child: CircularProgressIndicator(),
              ),
            ),
          if (error.isNotEmpty) Text(error, style: TextStyle(color: cs.error)),
          if (!loading && pending.isEmpty)
            Card(
              child: ListTile(
                leading: const Icon(Icons.check_circle_outline),
                title: const Text('Kutilayotgan tasdiq yo\'q'),
                subtitle: Text(
                  'ROBIN xavfli amaldan oldin shu yerda so\'raydi',
                  style: TextStyle(color: cs.outline),
                ),
              ),
            ),
          for (final a in pending)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Chip(
                          label: Text('${a['risk']}'),
                          backgroundColor: _risk(
                            '${a['risk']}',
                            cs,
                          ).withValues(alpha: .15),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            '${a['tool']}',
                            style: const TextStyle(
                              fontWeight: FontWeight.bold,
                              fontSize: 16,
                            ),
                          ),
                        ),
                      ],
                    ),
                    if ('${a['reason'] ?? ''}'.isNotEmpty)
                      Text('${a['reason']}'),
                    const SizedBox(height: 6),
                    Text(
                      const JsonEncoder.withIndent('  ').convert(a['args']),
                      style: TextStyle(
                        fontFamily: 'monospace',
                        fontSize: 12,
                        color: cs.outline,
                      ),
                      maxLines: 8,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton(
                            onPressed: () => _decide(a['id'], false),
                            child: const Text('❌ Rad etish'),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: FilledButton(
                            onPressed: () => _decide(a['id'], true),
                            child: const Text('✅ Ruxsat'),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          if (done.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(4, 16, 4, 4),
              child: Text('Tarix', style: TextStyle(color: cs.outline)),
            ),
          for (final a in done)
            ListTile(
              dense: true,
              leading: Icon(
                a['status'] == 'approved' ? Icons.check : Icons.close,
                color: a['status'] == 'approved' ? Colors.green : cs.error,
              ),
              title: Text('${a['tool']}'),
              subtitle: Text(
                '${a['status']} · ${a['created_at']}'
                    .replaceFirst('T', ' ')
                    .split('.')
                    .first,
              ),
            ),
        ],
      ),
    );
  }
}
