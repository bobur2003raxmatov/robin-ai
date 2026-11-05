import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';

import '../api.dart';

/// Notes: guides + what ROBIN wrote automatically (tasks, commands, lessons, daily journal).
class NotesScreen extends StatefulWidget {
  const NotesScreen({super.key});
  @override
  State<NotesScreen> createState() => _NotesScreenState();
}

class _NotesScreenState extends State<NotesScreen> {
  List items = [];
  String q = '', error = '';
  bool loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await Api.I.get('/api/notes?q=${Uri.encodeQueryComponent(q)}');
      if (mounted)
        setState(() {
          items = r['items'] as List;
          loading = false;
          error = '';
        });
    } catch (e) {
      if (mounted)
        setState(() {
          error = '$e';
          loading = false;
        });
    }
  }

  Future<void> _add() async {
    final t = TextEditingController(), b = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Yangi qayd'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: t,
              decoration: const InputDecoration(labelText: 'Sarlavha'),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: b,
              maxLines: 6,
              decoration: const InputDecoration(labelText: 'Matn'),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Bekor'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Saqlash'),
          ),
        ],
      ),
    );
    if (ok != true || t.text.trim().isEmpty) return;
    try {
      await Api.I.post('/api/notes', {
        'title': t.text.trim(),
        'body': b.text,
        'category': 'personal',
      });
      _load();
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      floatingActionButton: FloatingActionButton(
        onPressed: _add,
        child: const Icon(Icons.add),
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(12),
          children: [
            const Text(
              'Notes',
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 8),
            TextField(
              decoration: const InputDecoration(
                prefixIcon: Icon(Icons.search),
                hintText: 'Qidirish…',
                isDense: true,
              ),
              onSubmitted: (v) {
                q = v;
                _load();
              },
            ),
            const SizedBox(height: 8),
            if (loading)
              const Center(
                child: Padding(
                  padding: EdgeInsets.all(30),
                  child: CircularProgressIndicator(),
                ),
              ),
            if (error.isNotEmpty)
              Text(error, style: TextStyle(color: cs.error)),
            for (final n in items)
              Card(
                child: ListTile(
                  leading: Text(
                    n['system'] == true
                        ? '📘'
                        : (n['auto'] == true ? '🤖' : '📝'),
                    style: const TextStyle(fontSize: 22),
                  ),
                  title: Text(
                    '${n['title']}',
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                  subtitle: Text(
                    n['system'] == true
                        ? "yo'riqnoma"
                        : '${n['created_at'] ?? ''}'.split('T').first,
                  ),
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => Scaffold(
                        appBar: AppBar(title: Text('${n['title']}')),
                        body: Markdown(
                          data: '${n['body'] ?? ''}',
                          selectable: true,
                        ),
                      ),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
