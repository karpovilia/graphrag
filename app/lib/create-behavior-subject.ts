import { BehaviorSubject, type Subscription } from "rxjs";
import {
  type DeepReadonly,
  type Ref,
  type UnwrapNestedRefs,
  type UnwrapRef,
  onMounted,
  onUnmounted,
  readonly,
  ref,
} from "vue";

type IfAny<T, Y, N> = 0 extends 1 & T ? Y : N;
export function createBehaviorSubject<T>(initialValue: T): {
  next: (value: T) => void;
  subscribe: (callback: (value: T) => void) => Subscription;
  useSubscribe: () => DeepReadonly<
    UnwrapNestedRefs<
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      [T] extends [Ref<any, any>] ? IfAny<T, Ref<T, T>, T> : Ref<UnwrapRef<T>, T | UnwrapRef<T>>
    >
  >;
} {
  const sub = new BehaviorSubject<T>(initialValue);

  return {
    next: sub.next.bind(sub),
    // eslint-disable-next-line @typescript-eslint/no-deprecated
    subscribe: sub.subscribe.bind(sub),
    useSubscribe: () => {
      const subscribedValue = ref<T>(sub.value);
      let subscription: Subscription | undefined;

      onMounted(() => {
        subscription = sub.subscribe((val) => {
          subscribedValue.value = val;
        });
      });

      onUnmounted(() => {
        subscription?.unsubscribe?.();
      });

      return readonly(subscribedValue);
    },
  };
}
