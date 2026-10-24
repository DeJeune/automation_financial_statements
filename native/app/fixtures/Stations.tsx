// Start this test with an empty on-disk station list; subsequent opens use App.tsx.
import { Reports } from "financial/native";
import { mount } from "nsh";
import { Workstation } from "../Workstation";
import { template } from "./templates";

Reports.saveStations({ stations: [], selectedId: "" });
mount(() => (
  <Workstation
    initialFiles={{
      简表模板: [template()],
      油品时间统计: ["native/app/fixtures/stats.csv"],
      加油明细: ["native/app/fixtures/details.csv"],
      充值明细: ["native/app/fixtures/recharge.csv"],
    }}
  />
));
