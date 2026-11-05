import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../api.dart';
import '../main.dart';

/// First screen: connect to the ROBIN server — scan the pairing QR (no password) or log in manually.
class ConnectScreen extends StatefulWidget {
  const ConnectScreen({super.key});
  @override
  State<ConnectScreen> createState() => _ConnectScreenState();
}

class _ConnectScreenState extends State<ConnectScreen> {
  final server = TextEditingController(
    text: Api.I.server.isEmpty ? 'http://192.168.1.' : Api.I.server,
  );
  final user = TextEditingController();
  final pass = TextEditingController();
  bool busy = false;
  String error = '';

  void _done() => Navigator.of(context).pushAndRemoveUntil(
    MaterialPageRoute(builder: (_) => const HomeShell()),
    (_) => false,
  );

  Future<void> _run(Future<void> Function() f) async {
    setState(() {
      busy = true;
      error = '';
    });
    try {
      await f();
      if (mounted) _done();
    } catch (e) {
      setState(
        () =>
            error = e is ApiError ? e.message : "Serverga ulanib bo'lmadi: $e",
      );
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _scan() async {
    final raw = await Navigator.of(context)
        .push<String>(MaterialPageRoute(builder: (_) => const _QrPage()));
    if (raw == null) return;
    await _run(() => Api.I.pairWithQr(raw, 'Telefon'));
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            const SizedBox(height: 24),
            Center(
              child: Container(
                width: 84,
                height: 84,
                decoration: BoxDecoration(
                  color: brand,
                  borderRadius: BorderRadius.circular(24),
                ),
                alignment: Alignment.center,
                child: const Text(
                  'R',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 44,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ),
            const SizedBox(height: 14),
            const Center(
              child: Text(
                'ROBIN',
                style: TextStyle(fontSize: 28, fontWeight: FontWeight.w800),
              ),
            ),
            Center(
              child: Text(
                'Shaxsiy AI yordamchingiz',
                style: TextStyle(color: cs.outline),
              ),
            ),
            const SizedBox(height: 28),
            FilledButton.icon(
              onPressed: busy ? null : _scan,
              icon: const Icon(Icons.qr_code_scanner),
              label: const Padding(
                padding: EdgeInsets.all(14),
                child: Text('QR orqali ulanish (parolsiz)'),
              ),
            ),
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                'Kompyuterda: Dashboard → Download App → "📱 Telefonni ulash"',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 12, color: cs.outline),
              ),
            ),
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 18),
              child: Row(
                children: [
                  Expanded(child: Divider()),
                  Padding(
                    padding: EdgeInsets.symmetric(horizontal: 8),
                    child: Text('yoki'),
                  ),
                  Expanded(child: Divider()),
                ],
              ),
            ),
            TextField(
              controller: server,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(
                labelText: 'Server manzili',
                hintText: 'http://192.168.1.10:8000',
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: user,
              decoration: const InputDecoration(labelText: 'Login'),
              autocorrect: false,
            ),
            const SizedBox(height: 10),
            TextField(
              controller: pass,
              obscureText: true,
              decoration: const InputDecoration(labelText: 'Parol'),
            ),
            const SizedBox(height: 14),
            OutlinedButton(
              onPressed: busy
                  ? null
                  : () => _run(
                      () =>
                          Api.I.login(server.text, user.text.trim(), pass.text),
                    ),
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: busy
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Text('Kirish'),
              ),
            ),
            if (error.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text(error, style: TextStyle(color: cs.error)),
              ),
            const SizedBox(height: 18),
            Text(
              'Telefon va kompyuter bitta Wi-Fi tarmog\'ida bo\'lsin, serverda .env → HOST=0.0.0.0. '
              'Internet orqali ishlatish uchun HTTPS domen manzilini kiriting.',
              style: TextStyle(fontSize: 12, color: cs.outline),
            ),
          ],
        ),
      ),
    );
  }
}

class _QrPage extends StatefulWidget {
  const _QrPage();
  @override
  State<_QrPage> createState() => _QrPageState();
}

class _QrPageState extends State<_QrPage> {
  bool done = false;
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('QR kodni skanerlang')),
    body: MobileScanner(
      onDetect: (cap) {
        final v = cap.barcodes.isNotEmpty ? cap.barcodes.first.rawValue : null;
        if (done || v == null || !v.contains('"robin"')) return;
        done = true;
        Navigator.of(context).pop(v);
      },
    ),
  );
}
