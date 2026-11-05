import 'dart:convert';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:image_picker/image_picker.dart';
import 'package:speech_to_text/speech_to_text.dart';

import '../api.dart';

class _Msg {
  final String text;
  final bool me;
  final bool wait;
  _Msg(this.text, this.me, {this.wait = false});
}

/// Chat with ROBIN: text, voice (speech-to-text → ROBIN → server TTS), camera (Live Vision), ready-made commands.
class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});
  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final msgs = <_Msg>[];
  final input = TextEditingController();
  final scroll = ScrollController();
  final stt = SpeechToText();
  final player = AudioPlayer();
  String? conv;
  bool sending = false, listening = false, sttReady = false;
  List commands = [];
  String welcome = '';

  @override
  void initState() {
    super.initState();
    _loadPanel();
  }

  Future<void> _loadPanel() async {
    try {
      final p = await Api.I.get('/api/client/panel');
      setState(() {
        commands = p['commands'] ?? [];
        welcome = p['panel']?['welcome'] ?? '';
      });
    } catch (_) {}
  }

  void _down() => WidgetsBinding.instance.addPostFrameCallback((_) {
    if (scroll.hasClients)
      scroll.animateTo(
        scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
  });

  Future<void> _send({
    String text = '',
    String? commandId,
    String extra = '',
    String? imageB64,
    bool voice = false,
    String? shown,
  }) async {
    if (sending) return;
    setState(() {
      msgs.add(_Msg(shown ?? text, true));
      msgs.add(_Msg("ROBIN o'ylayapti…", false, wait: true));
      sending = true;
    });
    _down();
    try {
      final r = commandId != null
          ? await Api.I.post('/api/client/run', {
              'command_id': commandId,
              'extra': extra,
              'conversation_id': conv,
            })
          : await Api.I.post('/api/chat', {
              'text': text,
              'conversation_id': conv,
              'voice': voice,
              if (imageB64 != null) 'image_b64': imageB64,
              if (imageB64 != null) 'image_type': 'image/jpeg',
            });
      conv = r['conversation_id'] ?? conv;
      final reply = (r['reply'] ?? '') as String;
      setState(() {
        msgs.removeLast();
        msgs.add(_Msg(reply.isEmpty ? '(javob yo\'q)' : reply, false));
      });
      if (voice || Api.I.autoSpeak) _speak(reply);
    } catch (e) {
      setState(() {
        msgs.removeLast();
        msgs.add(_Msg('⚠️ $e', false));
      });
    } finally {
      setState(() => sending = false);
      _down();
    }
  }

  Future<void> _speak(String text) async {
    try {
      final r = await Api.I.post('/api/voice/tts', {'text': text});
      if (r['file'] != null)
        await player.play(
          UrlSource(Api.I.url('/api/voice/audio/${r['file']}')),
        );
    } catch (_) {}
  }

  Future<void> _mic() async {
    if (listening) {
      await stt.stop();
      setState(() => listening = false);
      return;
    }
    sttReady = sttReady || await stt.initialize();
    if (!sttReady) {
      _snack("Mikrofon / ovoz tanish mavjud emas");
      return;
    }
    await player.stop();
    setState(() => listening = true);
    final lang = '${Api.I.user?['language'] ?? 'uz'}';
    await stt.listen(
      listenOptions: SpeechListenOptions(
        partialResults: true,
        localeId: lang == 'ru' ? 'ru_RU' : (lang == 'en' ? 'en_US' : 'uz_UZ'),
      ),
      onResult: (r) {
        input.text = r.recognizedWords;
        if (r.finalResult) {
          setState(() => listening = false);
          final t = input.text.trim();
          input.clear();
          if (t.isNotEmpty) _send(text: t, voice: true);
        }
      },
    );
  }

  Future<void> _camera() async {
    final img = await ImagePicker().pickImage(
      source: ImageSource.camera,
      maxWidth: 1600,
      imageQuality: 80,
    );
    if (img == null) return;
    final b64 = base64Encode(await img.readAsBytes());
    final q = input.text.trim();
    input.clear();
    _send(
      text: q.isEmpty ? 'Bu rasmni tahlil qil.' : q,
      imageB64: b64,
      shown: '📷 ${q.isEmpty ? 'Rasm tahlili' : q}',
    );
  }

  Future<void> _command(Map c) async {
    final prompt = '${c['prompt']}';
    if (prompt.endsWith(':') || prompt.endsWith(' ')) {
      final ctl = TextEditingController();
      final extra = await showDialog<String>(
        context: context,
        builder: (_) => AlertDialog(
          title: Text('${c['icon']} ${c['title']}'),
          content: TextField(
            controller: ctl,
            autofocus: true,
            maxLines: 4,
            decoration: const InputDecoration(hintText: 'Matnni kiriting'),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Bekor'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, ctl.text),
              child: const Text('Yuborish'),
            ),
          ],
        ),
      );
      if (extra == null || extra.trim().isEmpty) return;
      _send(
        commandId: c['id'],
        extra: extra,
        shown: '${c['icon']} ${c['title']}: $extra',
      );
    } else {
      _send(commandId: c['id'], shown: '${c['icon']} ${c['title']}');
    }
  }

  void _snack(String t) =>
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t)));

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Column(
      children: [
        ListTile(
          title: const Text(
            'ROBIN',
            style: TextStyle(fontWeight: FontWeight.w800, fontSize: 20),
          ),
          subtitle: Text(
            Api.I.user?['full_name']?.toString().isNotEmpty == true
                ? 'Salom, ${Api.I.user!['full_name']}!'
                : 'AI yordamchi',
          ),
          trailing: IconButton(
            tooltip: 'Yangi suhbat',
            icon: const Icon(Icons.add_comment_outlined),
            onPressed: () => setState(() {
              conv = null;
              msgs.clear();
            }),
          ),
        ),
        if (commands.isNotEmpty)
          SizedBox(
            height: 44,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12),
              children: [
                for (final c in commands)
                  Padding(
                    padding: const EdgeInsets.only(right: 6),
                    child: ActionChip(
                      label: Text('${c['icon']} ${c['title']}'),
                      onPressed: sending ? null : () => _command(c),
                    ),
                  ),
              ],
            ),
          ),
        Expanded(
          child: msgs.isEmpty
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(28),
                    child: Text(
                      welcome.isEmpty
                          ? 'Savol bering yoki 🎤 bosib gapiring'
                          : welcome,
                      textAlign: TextAlign.center,
                      style: TextStyle(color: cs.outline),
                    ),
                  ),
                )
              : ListView.builder(
                  controller: scroll,
                  padding: const EdgeInsets.all(12),
                  itemCount: msgs.length,
                  itemBuilder: (_, i) {
                    final m = msgs[i];
                    return Align(
                      alignment: m.me
                          ? Alignment.centerRight
                          : Alignment.centerLeft,
                      child: Container(
                        margin: const EdgeInsets.symmetric(vertical: 4),
                        padding: const EdgeInsets.symmetric(
                          horizontal: 14,
                          vertical: 10,
                        ),
                        constraints: BoxConstraints(
                          maxWidth: MediaQuery.of(context).size.width * .86,
                        ),
                        decoration: BoxDecoration(
                          color: m.me ? cs.primary : cs.surfaceContainerHighest,
                          borderRadius: BorderRadius.circular(16),
                        ),
                        child: m.me
                            ? Text(
                                m.text,
                                style: TextStyle(color: cs.onPrimary),
                              )
                            : m.wait
                            ? Text(
                                m.text,
                                style: const TextStyle(
                                  fontStyle: FontStyle.italic,
                                ),
                              )
                            : GestureDetector(
                                onLongPress: () => _speak(m.text),
                                child: MarkdownBody(
                                  data: m.text,
                                  selectable: true,
                                ),
                              ),
                      ),
                    );
                  },
                ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(8, 4, 8, 8),
          child: Row(
            children: [
              IconButton(
                tooltip: 'Kamera (Live Vision)',
                icon: const Icon(Icons.photo_camera_outlined),
                onPressed: sending ? null : _camera,
              ),
              Expanded(
                child: TextField(
                  controller: input,
                  minLines: 1,
                  maxLines: 5,
                  textInputAction: TextInputAction.send,
                  onSubmitted: (t) {
                    if (t.trim().isEmpty) return;
                    input.clear();
                    _send(text: t.trim());
                  },
                  decoration: InputDecoration(
                    hintText: listening ? 'Tinglayapman…' : 'Xabar yozing…',
                    isDense: true,
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(24),
                    ),
                  ),
                ),
              ),
              IconButton.filledTonal(
                tooltip: 'Gapirish',
                icon: Icon(listening ? Icons.stop : Icons.mic),
                color: listening ? cs.error : null,
                onPressed: _mic,
              ),
              IconButton.filled(
                icon: sending
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.send),
                onPressed: sending
                    ? null
                    : () {
                        final t = input.text.trim();
                        if (t.isEmpty) return;
                        input.clear();
                        _send(text: t);
                      },
              ),
            ],
          ),
        ),
      ],
    );
  }
}
