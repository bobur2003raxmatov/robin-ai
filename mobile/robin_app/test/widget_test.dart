import 'package:flutter_test/flutter_test.dart';
import 'package:robin_app/api.dart';

void main() {
  test('server URL normalize', () {
    expect(Api.normalize('192.168.1.5:8000/'), 'http://192.168.1.5:8000');
    expect(Api.normalize('https://robin.uz'), 'https://robin.uz');
  });
}
