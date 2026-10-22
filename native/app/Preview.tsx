import { Reports, type TablePage } from "financial/native";
import { cleanup, effect, Image, Scroll, signal, Text, View } from "nsh";
import { Dialog } from "nsh/base";
import { Button, Label, palette } from "./controls";
export type PreviewRequest = { paths: string[]; index: number; image: boolean; title: string };
export function Preview(p: {
  request: PreviewRequest;
  onClose: () => void;
  onError: (e: unknown) => void;
}) {
  const index = signal(p.request.index),
    sheet = signal(""),
    offset = signal(0),
    table = signal<TablePage | null>(null),
    image = signal(""),
    loading = signal(false),
    zoom = signal(1),
    error = signal("");
  let generation = 0;
  cleanup(() => {
    generation++;
  });
  effect(() => {
    const current = ++generation;
    const path = p.request.paths[index()];
    const selected = sheet();
    const start = offset();
    loading.set(true);
    error.set("");
    const task = p.request.image
      ? Reports.imagePreview(path)
      : Reports.tablePreview(path, selected, start);
    task
      .then((result) => {
        if (current !== generation) return;
        if (typeof result === "string") image.set(result);
        else table.set(result);
      })
      .catch((e) => {
        if (current !== generation) return;
        error.set(String(e));
        p.onError(e);
      })
      .finally(() => {
        if (current === generation) loading.set(false);
      });
  });
  function move(delta: number) {
    index.set(index() + delta);
    offset.set(0);
    sheet.set("");
    zoom.set(1);
  }
  const letters = (n: number): string => {
    let s = "";
    for (n++; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
    return s;
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) p.onClose();
      }}
      style={{
        width: 960,
        height: 660,
        padding: 20,
        gap: 12,
        borderRadius: 12,
        backgroundColor: palette().card,
      }}
      backdropStyle={{ backgroundColor: "#00000077" }}
    >
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <Text style={{ fontSize: 18, fontWeight: "600", color: palette().ink }}>
          {p.request.title}
        </Text>
        <Button onPress={p.onClose}>关闭预览</Button>
      </View>
      <Label>{Reports.fileName(p.request.paths[index()])}</Label>
      <If when={loading()}>
        <Label>正在加载预览…</Label>
      </If>
      <If when={!!error()}>
        <Text style={{ color: palette().error }}>{error()}</Text>
      </If>
      <If when={p.request.image}>
        <Scroll style={{ flex: 1 }} horizontal contentStyle={{ minWidth: 900 }}>
          <Scroll style={{ width: 900 * zoom(), flex: 1 }}>
            <Image
              src={image()}
              resizeMode="contain"
              style={{ width: 900 * zoom(), height: 470 * zoom() }}
            />
          </Scroll>
        </Scroll>
        <View style={{ flexDirection: "row", gap: 10, alignItems: "center" }}>
          <Button disabled={index() === 0} onPress={() => move(-1)}>
            上一张
          </Button>
          <Label>{`${index() + 1} / ${p.request.paths.length}`}</Label>
          <Button disabled={index() === p.request.paths.length - 1} onPress={() => move(1)}>
            下一张
          </Button>
          <Button onPress={() => zoom.set(Math.max(0.5, zoom() - 0.25))}>缩小</Button>
          <Button onPress={() => zoom.set(Math.min(4, zoom() + 0.25))}>放大</Button>
          <Button onPress={() => zoom.set(1)}>适应窗口</Button>
        </View>
      </If>
      <If when={!p.request.image && !!table()}>
        <Scroll horizontal style={{ height: 40, flexGrow: 0 }} contentStyle={{ gap: 8 }}>
          <Each of={table()?.sheets || []}>
            {(name) => (
              <Button
                primary={table()?.sheet === name()}
                disabled={loading()}
                onPress={() => {
                  sheet.set(name());
                  offset.set(0);
                }}
              >
                {name()}
              </Button>
            )}
          </Each>
        </Scroll>
        <Scroll horizontal style={{ flex: 1 }}>
          <Scroll style={{ flex: 1 }} contentStyle={{ gap: 1 }}>
            <View style={{ flexDirection: "row", backgroundColor: palette().button }}>
              <Text style={{ width: 50, padding: 6, color: palette().muted }}>行</Text>
              {Array.from(
                { length: table()?.rows.reduce((n, r) => Math.max(n, r.length), 0) || 0 },
                (_, i) => (
                  <Text style={{ width: 120, padding: 6, color: palette().muted }}>
                    {letters(i)}
                  </Text>
                ),
              )}
            </View>
            <Each of={table()?.rows || []}>
              {(row, i) => (
                <View
                  style={{
                    flexDirection: "row",
                    borderBottomWidth: 1,
                    borderColor: palette().line,
                  }}
                >
                  <Text style={{ width: 50, padding: 6, fontSize: 12, color: palette().muted }}>
                    {String(offset() + i() + 1)}
                  </Text>
                  <Each of={row()}>
                    {(cell) => (
                      <Text
                        selectable
                        numberOfLines={3}
                        style={{ width: 120, padding: 6, fontSize: 12, color: palette().ink }}
                      >
                        {cell()}
                      </Text>
                    )}
                  </Each>
                </View>
              )}
            </Each>
          </Scroll>
        </Scroll>
        <View style={{ flexDirection: "row", gap: 10, alignItems: "center" }}>
          <Button
            disabled={offset() === 0 || loading()}
            onPress={() => offset.set(Math.max(0, offset() - 100))}
          >
            上一页
          </Button>
          <Label>{`第 ${offset() + 1}–${Math.min(offset() + 100, table()?.total || 0)} 行，共 ${table()?.total || 0} 行`}</Label>
          <Button
            disabled={offset() + 100 >= (table()?.total || 0) || loading()}
            onPress={() => offset.set(offset() + 100)}
          >
            下一页
          </Button>
        </View>
      </If>
    </Dialog>
  );
}
