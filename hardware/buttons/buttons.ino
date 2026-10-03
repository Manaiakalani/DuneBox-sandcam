// DuneBox physical buttons for an Arduino Uno, Nano, Leonardo or similar.
//
// Wire each button between a pin below and GND; no resistors are needed
// because the internal pull-ups are used. Arcade buttons with a built-in LED
// can light up while pressed: connect the LED (with its resistor) to the
// matching pin in LED_PINS, or set that entry to -1.
//
// Each press prints one line, "BTN 1" to "BTN 8", at 115200 baud. sandcam
// finds the board automatically once "Arduino buttons" is on in the
// dashboard, where you choose what each button does.

const int BUTTON_PINS[] = {2, 3, 4, 5, 6, 7, 8, 9};
const int LED_PINS[]    = {-1, -1, -1, -1, -1, -1, -1, -1};
const int COUNT = sizeof(BUTTON_PINS) / sizeof(BUTTON_PINS[0]);

const unsigned long DEBOUNCE_MS = 25;
const unsigned long REPEAT_GUARD_MS = 250;  // ignore bounces and impatient double-taps

bool pressed[COUNT];
unsigned long changedAt[COUNT];
unsigned long firedAt[COUNT];

void setup() {
  Serial.begin(115200);
  for (int i = 0; i < COUNT; i++) {
    pinMode(BUTTON_PINS[i], INPUT_PULLUP);
    if (LED_PINS[i] >= 0) pinMode(LED_PINS[i], OUTPUT);
    pressed[i] = false;
    changedAt[i] = 0;
    firedAt[i] = 0;
  }
}

void loop() {
  unsigned long now = millis();
  for (int i = 0; i < COUNT; i++) {
    bool down = digitalRead(BUTTON_PINS[i]) == LOW;
    if (down == pressed[i]) {
      changedAt[i] = now;
      continue;
    }
    if (now - changedAt[i] < DEBOUNCE_MS) continue;

    pressed[i] = down;
    changedAt[i] = now;
    if (LED_PINS[i] >= 0) digitalWrite(LED_PINS[i], down ? HIGH : LOW);
    if (down && now - firedAt[i] >= REPEAT_GUARD_MS) {
      firedAt[i] = now;
      Serial.print("BTN ");
      Serial.println(i + 1);
    }
  }
}
