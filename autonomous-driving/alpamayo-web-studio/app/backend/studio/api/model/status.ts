import { type AlpamayoGateway, type GatewayProvider } from "../../gateway/alpamayo-gateway.js";

export interface PublicModelStatus {
  ready: boolean;
  provider: GatewayProvider | null;
}

export async function modelStatus(gateway: AlpamayoGateway): Promise<PublicModelStatus> {
  const provider = await gateway.readyProvider();
  return { ready: provider !== null, provider };
}
