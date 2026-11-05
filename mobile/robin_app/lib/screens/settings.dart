import 'package:flutter/material.dart';

import '../api.dart';

class SettingsScreen extends StatefulWidget {
  final VoidCallback onLogout;
  const SettingsScreen({super.key, required this.onLogout});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  Map? usage;

  @override
  void initState() {
    super.initState();
    Api.I
        .get('/api/client/panel')
        .then((p) {
          if (mounted) setState(() => usage = p);
        })
        .catchError((_) {});
  }

  @override
  Widget build(BuildContext context) {
    final u = Api.I.user ?? {};
    final cs = Theme.of(context).colorScheme;
    final used = usage?['usage']?['daily_messages'] ?? 0;
    final lim = usage?['limits']?['daily_messages'] ?? 0;
    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        const Text(
          'Sozlamalar',
          style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
        ),
        const SizedBox(height: 8),
        Card(
          child: ListTile(
            leading: CircleAvatar(
              child: Text(
                ('${u['full_name'] ?? ''}'.isNotEmpty
                        ? '${u['full_name']}'
                        : '${u['username'] ?? '?'}')
                    .substring(0, 1)
                    .toUpperCase(),
              ),
            ),
            title: Text(
              '${u['full_name'] ?? ''}'.isNotEmpty
                  ? '${u['full_name']}'
                  : '@${u['username'] ?? ''}',
            ),
            subtitle: Text(
              '@${u['username'] ?? ''}${u['is_admin'] == true ? ' · admin' : ''}',
            ),
          ),
        ),
        Card(
          child: ListTile(
            leading: const Icon(Icons.dns_outlined),
            title: const Text('Server'),
            subtitle: Text(Api.I.server),
          ),
        ),
        Card(
          child: ListTile(
            leading: const Icon(Icons.bar_chart),
            title: const Text('Bugungi xabarlar'),
            subtitle: Text(lim == 0 ? '$used (cheklanmagan)' : '$used / $lim'),
          ),
        ),
        Card(
          child: SwitchListTile(
            secondary: const Icon(Icons.volume_up_outlined),
            title: const Text('Javoblarni ovoz chiqarib o\'qish'),
            subtitle: const Text(
              'Ovozli savollarga doim ovoz bilan javob beriladi',
            ),
            value: Api.I.autoSpeak,
            onChanged: (v) {
              setState(() => Api.I.autoSpeak = v);
              Api.I.save();
            },
          ),
        ),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          style: OutlinedButton.styleFrom(foregroundColor: cs.error),
          onPressed: widget.onLogout,
          icon: const Icon(Icons.logout),
          label: const Text('Chiqish'),
        ),
        const SizedBox(height: 16),
        Center(
          child: Text(
            'ROBIN mobil · v1.0.0',
            style: TextStyle(color: cs.outline, fontSize: 12),
          ),
        ),
      ],
    );
  }
}
