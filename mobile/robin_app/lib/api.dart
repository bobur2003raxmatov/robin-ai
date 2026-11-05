import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

class ApiError implements Exception {
  final int status;
  final String message;
  ApiError(this.status, this.message);
  @override
  String toString() => message;
}

/// ROBIN server connection: base URL + login token (persisted), REST helpers and the live WebSocket.
class Api {
  Api._();
  static final Api I = Api._();

  String server = '';
  String token = '';
  Map<String, dynamic>? user;
  bool autoSpeak = false;

  final _events = StreamController<Map<String, dynamic>>.broadcast();
  Stream<Map<String, dynamic>> get events => _events.stream;
  WebSocketChannel? _ws;
  Timer? _ping;
  bool _wsWanted = false;

  bool get loggedIn => server.isNotEmpty && token.isNotEmpty;
  bool get isAdmin => user?['is_admin'] == true;

  Future<void> load() async {
    final p = await SharedPreferences.getInstance();
    server = p.getString('server') ?? '';
    token = p.getString('token') ?? '';
    autoSpeak = p.getBool('auto_speak') ?? false;
    final u = p.getString('user');
    if (u != null) user = jsonDecode(u) as Map<String, dynamic>;
  }

  Future<void> save() async {
    final p = await SharedPreferences.getInstance();
    await p.setString('server', server);
    await p.setString('token', token);
    await p.setBool('auto_speak', autoSpeak);
    if (user != null) await p.setString('user', jsonEncode(user));
  }

  Future<void> logout() async {
    disconnect();
    token = '';
    user = null;
    final p = await SharedPreferences.getInstance();
    await p.remove('token');
    await p.remove('user');
  }

  static String normalize(String s) {
    var u = s.trim();
    if (u.isEmpty) return u;
    if (!u.startsWith('http://') && !u.startsWith('https://')) u = 'http://$u';
    while (u.endsWith('/')) {
      u = u.substring(0, u.length - 1);
    }
    return u;
  }

  Uri uri(String path) => Uri.parse('$server$path');
  String url(String path) => '$server$path';

  Map<String, String> get _headers => {
    'Content-Type': 'application/json',
    if (token.isNotEmpty) 'Authorization': 'Bearer $token',
  };

  dynamic _decode(http.Response r) {
    dynamic body;
    try {
      body = jsonDecode(utf8.decode(r.bodyBytes));
    } catch (_) {
      body = null;
    }
    if (r.statusCode >= 400) {
      final d = body is Map ? body['detail'] : null;
      throw ApiError(r.statusCode, d is String ? d : 'Xato ${r.statusCode}');
    }
    return body;
  }

  Future<dynamic> get(String path) async => _decode(
    await http
        .get(uri(path), headers: _headers)
        .timeout(const Duration(seconds: 30)),
  );

  Future<dynamic> post(
    String path, [
    Object? body,
    Duration timeout = const Duration(seconds: 240),
  ]) async => _decode(
    await http
        .post(uri(path), headers: _headers, body: jsonEncode(body ?? {}))
        .timeout(timeout),
  );

  Future<dynamic> put(String path, Object body) async => _decode(
    await http
        .put(uri(path), headers: _headers, body: jsonEncode(body))
        .timeout(const Duration(seconds: 30)),
  );

  // ---------------------------------------------------------------- auth
  Future<void> login(String srv, String username, String password) async {
    server = normalize(srv);
    token = '';
    final r = await post('/api/auth/login', {
      'username': username,
      'password': password,
    }, const Duration(seconds: 20));
    token = r['token'];
    user = Map<String, dynamic>.from(r['user']);
    await save();
  }

  /// QR payload from Dashboard → Download App → "Telefonni ulash": {"robin":1,"server":"…","code":"…"}
  Future<void> pairWithQr(String raw, String deviceName) async {
    final m = jsonDecode(raw);
    if (m is! Map || m['robin'] != 1)
      throw ApiError(400, "Bu ROBIN QR kodi emas");
    server = normalize(m['server']);
    token = '';
    final r = await post('/api/mobile/pair', {
      'code': m['code'],
      'device_name': deviceName,
    }, const Duration(seconds: 20));
    token = r['token'];
    user = Map<String, dynamic>.from(r['user']);
    await save();
  }

  Future<void> refreshMe() async {
    user = Map<String, dynamic>.from(await get('/api/auth/me'));
    await save();
  }

  // ---------------------------------------------------------------- realtime
  void connect() {
    _wsWanted = true;
    if (_ws != null || !loggedIn) return;
    final wsUrl = server.replaceFirst(RegExp(r'^http'), 'ws');
    try {
      final ch = WebSocketChannel.connect(Uri.parse('$wsUrl/ws?token=$token'));
      _ws = ch;
      ch.stream.listen(
        (m) {
          try {
            _events.add(Map<String, dynamic>.from(jsonDecode(m as String)));
          } catch (_) {}
        },
        onDone: _reconnect,
        onError: (_) => _reconnect(),
      );
      _ping?.cancel();
      _ping = Timer.periodic(const Duration(seconds: 25), (_) {
        try {
          _ws?.sink.add(jsonEncode({'type': 'ping'}));
        } catch (_) {}
      });
    } catch (_) {
      _reconnect();
    }
  }

  void _reconnect() {
    _ws = null;
    if (_wsWanted) Future.delayed(const Duration(seconds: 4), connect);
  }

  void disconnect() {
    _wsWanted = false;
    _ping?.cancel();
    _ws?.sink.close();
    _ws = null;
  }

  /// Streams NDJSON events from POST /api/claude/chat (admin).
  Stream<Map<String, dynamic>> claudeStream(String text) async* {
    final req = http.Request('POST', uri('/api/claude/chat'))
      ..headers.addAll(_headers)
      ..body = jsonEncode({'text': text});
    final client = http.Client();
    try {
      final res = await client.send(req);
      if (res.statusCode >= 400) {
        final body = await res.stream.bytesToString();
        String msg = 'Xato ${res.statusCode}';
        try {
          msg = jsonDecode(body)['detail'] ?? msg;
        } catch (_) {}
        yield {'t': 'error', 'text': msg};
        return;
      }
      final lines = res.stream
          .transform(utf8.decoder)
          .transform(const LineSplitter());
      await for (final l in lines) {
        if (l.trim().isEmpty) continue;
        try {
          yield Map<String, dynamic>.from(jsonDecode(l));
        } catch (_) {}
      }
    } finally {
      client.close();
    }
  }
}
