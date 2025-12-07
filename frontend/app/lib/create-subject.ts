import { Subject, type Subscription } from "rxjs";
import { onMounted, onUnmounted } from "vue";

export function createSubject<T>() {
  const sub = new Subject<T>();

  return {
    next: sub.next.bind(sub),
    // eslint-disable-next-line @typescript-eslint/no-deprecated
    subscribe: sub.subscribe.bind(sub),
    useSubscribe: (cb: (val: T) => void) => {
      let subscription: Subscription | undefined;

      onMounted(() => {
        subscription = sub.subscribe(cb);
      });

      onUnmounted(() => {
        subscription?.unsubscribe?.();
      });
    },
  };
}
