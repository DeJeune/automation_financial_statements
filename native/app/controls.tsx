import { Image, Input, type JSX, signal, Text, View } from "nsh";
import { Dialog, Button as NativeButton } from "nsh/base";
import eye from "./assets/eye.svg";
import eyeOff from "./assets/eye-off.svg";

export const typography = {
  title: { fontSize: 20, fontWeight: "600" },
  section: { fontSize: 14, fontWeight: "600" },
  item: { fontSize: 14, fontWeight: "500" },
  body: { fontSize: 14, fontWeight: "400" },
  file: { fontSize: 13, fontWeight: "400" },
  caption: { fontSize: 12, fontWeight: "400" },
} as const;
export const theme = signal("light");
export const palette = () =>
  theme() === "dark"
    ? {
        bg: "#17231F",
        card: "#21312B",
        ink: "#ECF3EE",
        muted: "#B2C3B9",
        line: "#3B5045",
        button: "#314A3D",
        green: "#9AD6B5",
        primary: "#347557",
        error: "#FFB2A4",
      }
    : {
        bg: "#F4F6F2",
        card: "#FFFFFF",
        ink: "#192F24",
        muted: "#63776A",
        line: "#DEE6DD",
        button: "#EDF2EA",
        green: "#216540",
        primary: "#216540",
        error: "#AD3529",
      };
export function Button(p: {
  children: string;
  onPress: () => void;
  disabled?: boolean;
  primary?: boolean;
  compact?: boolean;
  quiet?: boolean;
  testID?: string;
}) {
  return (
    <NativeButton
      testID={p.testID}
      accessibilityLabel={p.children}
      disabled={p.disabled}
      onPress={p.onPress}
      style={{
        paddingHorizontal: p.compact ? 9 : 14,
        paddingVertical: p.compact ? 6 : 10,
        borderRadius: 7,
        backgroundColor: p.primary ? palette().primary : p.quiet ? "transparent" : palette().button,
      }}
      hoverStyle={{
        opacity: 0.82,
        backgroundColor: p.primary ? palette().primary : palette().button,
      }}
      activeStyle={{ opacity: 0.65 }}
      disabledStyle={{ opacity: 0.4 }}
    >
      <Text
        style={{
          fontSize: 13,
          fontWeight: p.primary ? "500" : "400",
          color: p.primary ? "#FFFFFF" : palette().ink,
        }}
      >
        {p.children}
      </Text>
    </NativeButton>
  );
}
export function Label(p: { children: string }) {
  return <Text style={{ ...typography.caption, color: palette().muted }}>{p.children}</Text>;
}
export function Card(p: { title: string; children: JSX.Element }) {
  return (
    <View
      style={{
        gap: 14,
        padding: 20,
        borderRadius: 12,
        borderWidth: 1,
        borderColor: palette().line,
        backgroundColor: palette().card,
      }}
    >
      <Text style={{ ...typography.section, color: palette().ink }}>{p.title}</Text>
      {p.children}
    </View>
  );
}
export function Field(p: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  masked?: boolean;
  testID?: string;
  placeholder?: string;
}) {
  const revealed = signal(false);
  return (
    <View style={{ flex: 1, minWidth: 140, gap: 7 }}>
      <Label>{p.label}</Label>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          borderWidth: 1,
          borderColor: palette().line,
          borderRadius: 7,
          backgroundColor: palette().card,
        }}
      >
        <Input
          testID={p.testID}
          accessibilityLabel={p.label}
          value={p.value}
          readonly={p.disabled}
          masked={p.masked && !revealed()}
          autoCorrect={false}
          placeholder={p.placeholder || ""}
          onChange={p.onChange}
          style={{
            flex: 1,
            padding: 10,
            ...typography.body,
            color: palette().ink,
            backgroundColor: palette().card,
            borderRadius: 7,
          }}
        />
        <If when={p.masked}>
          <NativeButton
            testID={`${p.testID || "secret"}-visibility`}
            accessibilityLabel={`${revealed() ? "隐藏" : "显示"} ${p.label}`}
            disabled={p.disabled}
            onPress={() => revealed.set(!revealed())}
            style={{ padding: 10, borderRadius: 7 }}
            hoverStyle={{ backgroundColor: palette().button }}
            disabledStyle={{ opacity: 0.4 }}
          >
            <Image
              src={revealed() ? eyeOff : eye}
              style={{ width: 20, height: 20, tintColor: palette().muted }}
            />
          </NativeButton>
        </If>
      </View>
    </View>
  );
}
export const dateString = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const timeString = (d: Date) =>
  `${dateString(d)} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;

function TimePart(p: {
  label: string;
  value: string;
  max: number;
  testID: string;
  onChange: (v: string) => void;
}) {
  function step(delta: number) {
    const value = Number(p.value) || 0;
    p.onChange(String((value + delta + p.max + 1) % (p.max + 1)).padStart(2, "0"));
  }
  return (
    <View style={{ flex: 1, gap: 5 }}>
      <Label>{p.label}</Label>
      <View
        style={{
          flexDirection: "row",
          borderWidth: 1,
          borderColor: palette().line,
          borderRadius: 7,
        }}
      >
        <Input
          testID={p.testID}
          accessibilityLabel={p.label}
          value={p.value}
          onChange={(v) => {
            if (/^\d{0,2}$/.test(v)) p.onChange(v);
          }}
          autoCorrect={false}
          style={{ flex: 1, padding: 9, fontSize: 16, color: palette().ink, textAlign: "center" }}
        />
        <View>
          <NativeButton
            accessibilityLabel={`增加${p.label}`}
            onPress={() => step(1)}
            style={{
              width: 28,
              height: 22,
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: palette().button,
            }}
          >
            <Text style={{ color: palette().ink, fontSize: 12 }}>＋</Text>
          </NativeButton>
          <NativeButton
            accessibilityLabel={`减少${p.label}`}
            onPress={() => step(-1)}
            style={{
              width: 28,
              height: 22,
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: palette().button,
            }}
          >
            <Text style={{ color: palette().ink, fontSize: 12 }}>−</Text>
          </NativeButton>
        </View>
      </View>
    </View>
  );
}

export function DateField(p: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
  testID: string;
  withTime?: boolean;
}) {
  const opened = signal(false),
    month = signal(0),
    year = signal(0),
    selected = signal(""),
    hours = signal("00"),
    minutes = signal("00"),
    seconds = signal("00");
  const validTime = () =>
    [
      [hours(), 23],
      [minutes(), 59],
      [seconds(), 59],
    ].every(([value, max]) => /^\d{1,2}$/.test(String(value)) && Number(value) <= Number(max));
  function setDraft(d: Date) {
    year.set(d.getFullYear());
    month.set(d.getMonth());
    selected.set(dateString(d));
    hours.set(String(d.getHours()).padStart(2, "0"));
    minutes.set(String(d.getMinutes()).padStart(2, "0"));
    seconds.set(String(d.getSeconds()).padStart(2, "0"));
  }
  function show() {
    const match = /^(\d{4})-(\d{2})-(\d{2})(?: (\d{2}):(\d{2}):(\d{2}))?$/.exec(p.value);
    setDraft(
      match
        ? new Date(
            Number(match[1]),
            Number(match[2]) - 1,
            Number(match[3]),
            Number(match[4] || 0),
            Number(match[5] || 0),
            Number(match[6] || 0),
          )
        : new Date(),
    );
    opened.set(true);
  }
  function move(delta: number) {
    const d = new Date(year(), month() + delta, 1);
    year.set(d.getFullYear());
    month.set(d.getMonth());
  }
  function choose(day: number) {
    const d = new Date(year(), month(), day);
    selected.set(dateString(d));
    if (!p.withTime) {
      p.onChange(dateString(d));
      opened.set(false);
    }
  }
  const days = () => {
    const start = new Date(year(), month(), 1).getDay();
    const end = new Date(year(), month() + 1, 0).getDate();
    return Array.from({ length: 42 }, (_, i) =>
      i >= start && i < start + end ? i - start + 1 : 0,
    );
  };
  return (
    <View style={{ flex: 1, minWidth: p.withTime ? 285 : 230, gap: 7 }}>
      <Label>{p.label}</Label>
      <View style={{ flexDirection: "row", gap: 6, alignItems: "center" }}>
        <Input
          testID={p.testID}
          accessibilityLabel={p.label}
          value={p.value}
          readonly={p.disabled}
          onChange={p.onChange}
          autoCorrect={false}
          placeholder={p.withTime ? "YYYY-MM-DD HH:mm:ss" : "YYYY-MM-DD"}
          style={{
            flex: 1,
            padding: 10,
            ...typography.body,
            fontVariant: ["tabular-nums"],
            color: palette().ink,
            borderWidth: 1,
            borderColor: palette().line,
            borderRadius: 7,
          }}
        />
        <Button testID={`${p.testID}-calendar`} disabled={p.disabled} onPress={show}>
          {p.withTime ? "日期时间" : "日历"}
        </Button>
      </View>
      <Dialog
        open={opened()}
        animation="none"
        onOpenChange={(v) => opened.set(v)}
        style={{
          margin: "auto",
          width: 360,
          padding: 20,
          gap: 16,
          borderRadius: 12,
          backgroundColor: palette().card,
        }}
        backdropStyle={{ backgroundColor: "#00000066" }}
      >
        <Text style={{ fontSize: 16, color: palette().ink, fontWeight: "600" }}>{p.label}</Text>
        <View
          style={{
            flexDirection: "row",
            gap: 8,
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <Button onPress={() => move(-12)}>«</Button>
          <Button onPress={() => move(-1)}>上月</Button>
          <Text
            style={{ color: palette().ink, fontSize: 14 }}
          >{`${year()}年${month() + 1}月`}</Text>
          <Button onPress={() => move(1)}>下月</Button>
          <Button onPress={() => move(12)}>»</Button>
        </View>
        <View style={{ flexDirection: "row", flexWrap: "wrap", width: 308, gap: 2 }}>
          {["日", "一", "二", "三", "四", "五", "六"].map((v) => (
            <Text style={{ width: 42, textAlign: "center", color: palette().muted, fontSize: 12 }}>
              {v}
            </Text>
          ))}
          <Each of={days()}>
            {(day) => (
              <NativeButton
                disabled={!day()}
                onPress={() => choose(day())}
                accessibilityLabel={`${year()}-${month() + 1}-${day()}`}
                style={{
                  width: 42,
                  height: 34,
                  alignItems: "center",
                  justifyContent: "center",
                  borderRadius: 5,
                  backgroundColor:
                    day() && selected() === dateString(new Date(year(), month(), day()))
                      ? palette().primary
                      : palette().button,
                }}
              >
                <Text
                  style={{
                    color:
                      day() && selected() === dateString(new Date(year(), month(), day()))
                        ? "#FFFFFF"
                        : palette().ink,
                    fontSize: 13,
                  }}
                >
                  {day() ? String(day()) : ""}
                </Text>
              </NativeButton>
            )}
          </Each>
        </View>
        <If when={p.withTime}>
          <View style={{ flexDirection: "row", gap: 10 }}>
            <TimePart
              label="时"
              testID={`${p.testID}-hours`}
              value={hours()}
              max={23}
              onChange={(v) => hours.set(v)}
            />
            <TimePart
              label="分"
              testID={`${p.testID}-minutes`}
              value={minutes()}
              max={59}
              onChange={(v) => minutes.set(v)}
            />
            <TimePart
              label="秒"
              testID={`${p.testID}-seconds`}
              value={seconds()}
              max={59}
              onChange={(v) => seconds.set(v)}
            />
          </View>
        </If>
        <View style={{ flexDirection: "row", gap: 8 }}>
          <Button
            onPress={() => {
              if (p.withTime) setDraft(new Date());
              else {
                p.onChange(dateString(new Date()));
                opened.set(false);
              }
            }}
          >
            {p.withTime ? "现在" : "今天"}
          </Button>
          <Button onPress={() => opened.set(false)}>{p.withTime ? "取消" : "关闭日历"}</Button>
          <If when={p.withTime}>
            <Button
              primary
              disabled={!validTime()}
              onPress={() => {
                p.onChange(
                  `${selected()} ${hours().padStart(2, "0")}:${minutes().padStart(2, "0")}:${seconds().padStart(2, "0")}`,
                );
                opened.set(false);
              }}
            >
              确定
            </Button>
          </If>
        </View>
      </Dialog>
    </View>
  );
}

export function PriceField(p: { value: string; onChange: (v: string) => void; disabled: boolean }) {
  function step(delta: number) {
    const current = Number(p.value);
    p.onChange(
      Math.min(10000, Math.max(0.01, (Number.isFinite(current) ? current : 8.23) + delta)).toFixed(
        2,
      ),
    );
  }
  function normalize() {
    const value = Number(p.value);
    if (Number.isFinite(value) && value >= 0.01 && value <= 10000) p.onChange(value.toFixed(2));
  }
  return (
    <View style={{ flex: 1, minWidth: 210, gap: 7 }}>
      <Label>#92 汽油价格</Label>
      <View style={{ flexDirection: "row", gap: 6, alignItems: "center" }}>
        <Button disabled={p.disabled} onPress={() => step(-0.01)}>
          −
        </Button>
        <Input
          testID="gas-price"
          accessibilityLabel="#92 汽油价格"
          value={p.value}
          readonly={p.disabled}
          onChange={p.onChange}
          onBlur={normalize}
          style={{
            flex: 1,
            padding: 10,
            ...typography.body,
            fontVariant: ["tabular-nums"],
            color: palette().ink,
            borderWidth: 1,
            borderColor: palette().line,
            borderRadius: 7,
          }}
        />
        <Button disabled={p.disabled} onPress={() => step(0.01)}>
          ＋
        </Button>
      </View>
    </View>
  );
}
