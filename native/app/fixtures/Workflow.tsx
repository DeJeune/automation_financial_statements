// Test entry: seed only file selection; all processing and preview use production code.
import { mount } from "nsh";
import { Workstation } from "../Workstation";

mount(() => (
  <Workstation
    persistStations={false}
    initialFiles={{
      日报模板: ["native/app/fixtures/invalid-daily.xlsx"],
      简表模板: ["native/app/fixtures/simple.xlsx"],
      油品时间统计: ["native/app/fixtures/stats.csv"],
      加油明细: ["native/app/fixtures/details.csv"],
      充值明细: ["native/app/fixtures/recharge.csv"],
    }}
  />
));
