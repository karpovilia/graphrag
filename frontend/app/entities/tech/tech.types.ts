import type { Message, Notification } from "@krainovsd/vue-ui";

export type IMessageSubjectPayload =
  | string
  | (Omit<Message, "id"> & {
      id?: number;
    });
export type INotificationSubjectPayload = Omit<Notification, "id"> & { id?: number };
