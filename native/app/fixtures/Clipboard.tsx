// NSH headless supports clipboard text only. Supply its missing file/image boundary here;
// file selection, validation, keyboard handling and upload state use the production code.
import { mount } from "nsh";
import { Clipboard } from "nsh/clipboard";
import { Workstation } from "../Workstation";

mount(() => (
  <Workstation
    persistStations={false}
    clipboard={{
      readFiles: async () => {
        const text = await Clipboard.readText();
        return text.startsWith("files:") ? text.slice(6).split("\n") : [];
      },
      readText: () => Clipboard.readText(),
      readImage: async () => null,
    }}
  />
));
