// Verify UI job routing; Rust tests cover recognition, arithmetic and saved workbooks.
import { mount } from "nsh";
import { Workstation } from "../Workstation";

mount(() => (
  <Workstation
    persistStations={false}
    initialFiles={{
      日报模板: ["native/app/fixtures/daily.xlsx"],
      简表模板: ["native/app/fixtures/simple.xlsx"],
      油品时间统计: ["native/app/fixtures/stats.csv"],
      油品优惠: ["native/app/fixtures/discounts.csv"],
      加油明细: ["native/app/fixtures/details.csv"],
      充值明细: ["native/app/fixtures/recharge.csv"],
      超市销售收入: ["native/app/fixtures/receipt.png"],
      POS: ["native/app/fixtures/receipt.png"],
    }}
    prepare={async (job) => {
      if (job.kind === "simple") {
        if (
          job.dailyResultId !== "daily-supermarket" ||
          job.files.filter((file) => file.category === "超市销售收入").length !== 1 ||
          job.files.some((file) => file.category === "POS")
        )
          throw new Error("简表没有收到本次日报结果和超市截图");
      }
      return {
        id: `${job.kind}-supermarket`,
        kind: job.kind,
        cells: [],
        notes: [],
        savedPath: job.template,
        backupPath: "",
      };
    }}
  />
));
