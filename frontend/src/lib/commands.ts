/**
 * Where the store posts commands to the server.
 *
 * The store is plain state and knows nothing about sockets, while the socket
 * lives in `useTerminal` — but toggling an indicator is a store action that
 * has to reach the backend. This is the one seam between them. It is a
 * module-level sink rather than a field in the store because a live socket
 * handle is not state a component should ever re-render on.
 *
 * With no sink installed — unit tests, or the moments before the terminal
 * mounts — commands are dropped rather than throwing. The socket already
 * replays what matters on connect, so nothing durable is lost.
 */

import type { ClientCommand } from '@/types/protocol';

let sink: ((command: ClientCommand) => void) | null = null;

export function setCommandSink(next: ((command: ClientCommand) => void) | null): void {
  sink = next;
}

export function sendCommand(command: ClientCommand): void {
  sink?.(command);
}
