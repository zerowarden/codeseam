interface Loader {
  load(path: string): Result;
}

abstract class BaseService {
  abstract run(value: string): string;
}

class Service {
  get value(): string {
    return this.inner.value;
  }

  set value(next: string) {
    this.inner.value = next;
  }

  constructor(private readonly inner: InnerService) {}

  execute(path: string): Result;
  execute(path: URL): Result;
  execute(path: string | URL): Result {
    return this.inner.execute(path);
  }

  query(path: string): Result {
    return this.inner.query(path);
  }
}

export function useRecordState(id: string): State {
  const value = useMemo(() => load(id), [id]);
  useEffect(() => {
    log(value);
  }, [value]);
  return value;
}

export function RecordPanel(props: Props): JSX.Element {
  return <section>{props.title}</section>;
}

export const InlinePanel = (props: Props): JSX.Element => (
  <section>{props.title}</section>
);

export const mapStateToProps = (state: AppState) => {
  return { themeId: state.settings.theme };
};

export const isListNode = function (node: Element) {
  return node && /^(OL|UL|DL)$/.test(node.nodeName);
};

class SyncTargetLike {
  protected hasUuid(): boolean {
    return false;
  }

  public static supportsShare(): boolean {
    return true;
  }

  initSynchronizer(): Synchronizer {
    return this.synchronizer;
  }
}

export const runtime = (): CommandRuntime => {
  return {
    execute: async (context: CommandContext) => {
      await CommandService.instance().execute('switchProfile', context.profileId);
    },
  };
};

export function registerExportCommand(registry: CommandRegistry): CommandDeclaration {
  return {
    name: 'exportNote',
    label: 'Export note',
    execute: () => registry.execute('exportNote'),
  };
}
