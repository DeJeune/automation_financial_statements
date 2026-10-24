// The real native processor merges both periods and supports different prices.
import { mount } from "nsh";
import { Workstation } from "../Workstation";
import { template } from "./templates";

mount(() => (
  <Workstation
    persistStations={false}
    initialFiles={{
      简表模板: [template()],
      油品时间统计: ["native/app/fixtures/price-before.csv"],
      "油品时间统计(调价后)": ["native/app/fixtures/price-after.csv"],
      加油明细: ["native/app/fixtures/price-details.csv"],
      充值明细: ["native/app/fixtures/recharge.csv"],
    }}
  />
));
