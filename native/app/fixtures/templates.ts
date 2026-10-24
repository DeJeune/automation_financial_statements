import { TestFiles } from "financial/native";

// Real write-back must target disposable copies, never the committed fixtures.
export const template = (name = "simple.xlsx") => TestFiles.template(name);
