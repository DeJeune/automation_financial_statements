// The gate controls timing only. Every released job uses the real Rust processor.
import { Reports } from "financial/native";
import { mount, signal, View } from "nsh";
import { Button } from "../controls";
import { Workstation } from "../Workstation";
import { template } from "./templates";

const files = {
  简表模板: [template()],
  油品时间统计: ["native/app/fixtures/stats.csv"],
  加油明细: ["native/app/fixtures/details.csv"],
  充值明细: ["native/app/fixtures/recharge.csv"],
};
const clipboard = signal([template()]);
const release = signal<(() => void) | null>(null);
let releasePaste: (() => void) | null = null;
const delayPaste = signal(false);
mount(() => (
  <View style={{ flex: 1 }}>
    <View style={{ flexDirection: "row", gap: 6 }}>
      {Object.entries(files).map(([category, paths]) => (
        <Button onPress={() => clipboard.set(category.endsWith("模板") ? [template()] : paths)}>
          {`复制${category}`}
        </Button>
      ))}
      <Button
        testID="release-job"
        disabled={!release()}
        onPress={() => {
          const resolve = release();
          release.set(null);
          resolve?.();
        }}
      >
        完成后台测试任务
      </Button>
      <Button onPress={() => delayPaste.set(true)}>延迟粘贴</Button>
      <Button
        onPress={() => {
          delayPaste.set(false);
          releasePaste?.();
          releasePaste = null;
        }}
      >
        完成粘贴
      </Button>
    </View>
    <Workstation
      persistStations={false}
      initialFiles={files}
      clipboard={{
        readFiles: async () => {
          const paths = clipboard();
          if (delayPaste())
            await new Promise<void>((resolve) => {
              releasePaste = resolve;
            });
          return paths;
        },
        readImage: async () => null,
        readText: async () => "",
      }}
      prepare={async (job) => {
        await new Promise<void>((resolve) => release.set(resolve));
        return Reports.prepare(job);
      }}
    />
  </View>
));
