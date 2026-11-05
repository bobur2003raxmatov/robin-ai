import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

import 'api.dart';
import 'screens/approvals.dart';
import 'screens/chat.dart';
import 'screens/claude.dart';
import 'screens/connect.dart';
import 'screens/notes.dart';
import 'screens/settings.dart';

final notifier = FlutterLocalNotificationsPlugin();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Api.I.load();
  try {
    await notifier.initialize(
      settings: const InitializationSettings(
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
        iOS: DarwinInitializationSettings(),
      ),
    );
    await notifier
        .resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin
        >()
        ?.requestNotificationsPermission();
  } catch (_) {}
  runApp(const RobinApp());
}

Future<void> showLocal(String title, String body) async {
  try {
    await notifier.show(
      id: DateTime.now().millisecondsSinceEpoch ~/ 1000 % 100000,
      title: title,
      body: body,
      notificationDetails: const NotificationDetails(
        android: AndroidNotificationDetails(
          'robin',
          'ROBIN',
          importance: Importance.high,
          priority: Priority.high,
        ),
        iOS: DarwinNotificationDetails(),
      ),
    );
  } catch (_) {}
}

const brand = Color(0xFF6D5DFC);

class RobinApp extends StatelessWidget {
  const RobinApp({super.key});

  ThemeData _theme(Brightness b) => ThemeData(
    useMaterial3: true,
    colorScheme: ColorScheme.fromSeed(seedColor: brand, brightness: b),
    inputDecorationTheme: const InputDecorationTheme(
      border: OutlineInputBorder(),
    ),
  );

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'ROBIN',
    debugShowCheckedModeBanner: false,
    theme: _theme(Brightness.light),
    darkTheme: _theme(Brightness.dark),
    home: Api.I.loggedIn ? const HomeShell() : const ConnectScreen(),
  );
}

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});
  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int idx = 0;
  int pending = 0;
  StreamSubscription? _sub;

  @override
  void initState() {
    super.initState();
    Api.I.connect();
    Api.I.refreshMe().then((_) => mounted ? setState(() {}) : null).catchError((
      e,
    ) {
      if (e is ApiError && e.status == 401) _toLogin();
    });
    _sub = Api.I.events.listen((m) {
      if (m['type'] == 'notification')
        showLocal('${m['title'] ?? 'ROBIN'}', '${m['body'] ?? ''}');
      if (m['type'] == 'approval_request') {
        setState(() => pending++);
        showLocal('Tasdiq kerak: ${m['tool']}', '${m['reason'] ?? ''}');
      }
    });
  }

  void _toLogin() async {
    await Api.I.logout();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const ConnectScreen()),
      (_) => false,
    );
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final admin = Api.I.isAdmin;
    final pages = <Widget>[
      const ChatScreen(),
      ApprovalsScreen(onChanged: () => setState(() => pending = 0)),
      const NotesScreen(),
      if (admin) const ClaudeScreen(),
      SettingsScreen(onLogout: _toLogin),
    ];
    final dests = <NavigationDestination>[
      const NavigationDestination(
        icon: Icon(Icons.chat_bubble_outline),
        selectedIcon: Icon(Icons.chat_bubble),
        label: 'Chat',
      ),
      NavigationDestination(
        icon: Badge(
          isLabelVisible: pending > 0,
          label: Text('$pending'),
          child: const Icon(Icons.verified_user_outlined),
        ),
        label: 'Tasdiq',
      ),
      const NavigationDestination(
        icon: Icon(Icons.sticky_note_2_outlined),
        label: 'Notes',
      ),
      if (admin)
        const NavigationDestination(
          icon: Text('🤖', style: TextStyle(fontSize: 22)),
          label: 'Claude',
        ),
      const NavigationDestination(
        icon: Icon(Icons.settings_outlined),
        label: 'Sozlama',
      ),
    ];
    if (idx >= pages.length) idx = 0;
    return Scaffold(
      body: SafeArea(
        child: IndexedStack(index: idx, children: pages),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: idx,
        destinations: dests,
        onDestinationSelected: (i) => setState(() => idx = i),
      ),
    );
  }
}
