import type { ThemeName } from "@krainovsd/vue-ui";
import { createBehaviorSubject } from "@/lib/create-behavior-subject";
import { createSubject } from "@/lib/create-subject";
// import { setToStorage } from "@/lib/set-to-storage";
import type { IMessageSubjectPayload, INotificationSubjectPayload } from "./tech.types";

// const THEME_STORAGE_KEY = "__themes__";
export const themeBehaviorSubject = createBehaviorSubject<ThemeName>("light");
// themeBehaviorSubject.subscribe((val) => {
//   setToStorage(THEME_STORAGE_KEY, val);
// });

export const notificationSubject = createSubject<INotificationSubjectPayload>();
export const messageSubject = createSubject<IMessageSubjectPayload>();
