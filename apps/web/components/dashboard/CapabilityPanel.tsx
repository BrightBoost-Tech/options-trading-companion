"use client";

import { useEffect, useState } from "react";
import {
    CapabilityState,
    fetchCapabilities,
    UpgradeCapability,
    CapabilityDisplayNames,
    CapabilityDescriptions
} from "@/lib/capabilities";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Lock, Unlock, Info } from "lucide-react";
import { QuantumTooltip } from "@/components/ui/QuantumTooltip";

export function CapabilityPanel() {
    const [capabilities, setCapabilities] = useState<CapabilityState[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let mounted = true;
        fetchCapabilities().then(data => {
            if (mounted && data.capabilities) {
                setCapabilities(data.capabilities);
            }
            if (mounted) setLoading(false);
        });
        return () => { mounted = false; };
    }, []);

    if (loading) return null; // Or a skeleton

    // Sort: Active first
    const sorted = [...capabilities].sort((a, b) =>
        (a.is_active === b.is_active) ? 0 : a.is_active ? -1 : 1
    );

    if (sorted.length === 0) return null;

    return (
        <Card>
            <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium flex items-center justify-between">
                    <span>System Upgrades</span>
                    <Badge variant="outline" className="text-xs font-normal">
                        {sorted.filter(c => c.is_active).length} / {sorted.length} Unlocked
                    </Badge>
                </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
                {sorted.map((cap) => (
                    <div key={cap.capability} className="flex items-start justify-between space-x-2">
                        <div className="flex flex-col space-y-1">
                            <div className="flex items-center space-x-2">
                                {cap.is_active ? (
                                    <Unlock className="h-3 w-3 text-emerald-500" />
                                ) : (
                                    <Lock className="h-3 w-3 text-muted-foreground" />
                                )}
                                <span className={`text-sm font-medium ${cap.is_active ? 'text-foreground' : 'text-muted-foreground'}`}>
                                    {CapabilityDisplayNames[cap.capability]}
                                </span>
                                <QuantumTooltip content={CapabilityDescriptions[cap.capability]}>
                                     <Info className="h-3 w-3 text-muted-foreground cursor-help" />
                                </QuantumTooltip>
                            </div>
                            {cap.reason && (
                                <span className="text-xs text-muted-foreground pl-5">
                                    {cap.reason}
                                </span>
                            )}
                        </div>
                        {cap.is_active && (
                            <Badge variant="secondary" className="text-[10px] h-5 bg-emerald-500/10 text-emerald-500 hover:bg-emerald-500/20 border-0">
                                Active
                            </Badge>
                        )}
                    </div>
                ))}
            </CardContent>
        </Card>
    );
}
