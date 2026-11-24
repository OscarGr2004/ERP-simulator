"""
Agente Inteligente: TransactGuard AI
Tema: Integridad de las Transacciones en ERP
Alumno: Oscar Octavio García Maya (Matrícula: 182889)
"""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Any
from neo4j import GraphDatabase


@dataclass
class IncidenciaIntegridad:
    regla_id: str
    severidad: str
    documento_id: str
    tipo_documento: str
    descripcion: str
    accion_planificada: str
    area_escalamiento: str


class TransactGuardAgent:
    TOLERANCIA_MONTO_PCT = 0.02

    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.incidencias: List[IncidenciaIntegridad] = []

    def cerrar(self):
        self.driver.close()

    def percibir_ciclo_compras_pagos(self) -> List[Dict[str, Any]]:
        query = """
        MATCH (f:Factura)
        OPTIONAL MATCH (f)-[:FACTURA_DE]->(oc:OrdenCompra)
        OPTIONAL MATCH (f)-[:AMPARADA_POR]->(r:Recepcion)
        OPTIONAL MATCH (u_crea:Usuario)-[:CREA]->(oc)
        OPTIONAL MATCH (u_apr:Usuario)-[:APRUEBA]->(oc)
        OPTIONAL MATCH (pg:Pago)-[:LIQUIDA]->(f)
        RETURN
            f.id AS factura_id,
            f.monto AS factura_monto,
            f.estado AS factura_estado,
            oc.id AS oc_id,
            oc.monto AS oc_monto,
            r.id AS recepcion_id,
            u_crea.id AS creador_id,
            u_crea.nombre AS creador_nombre,
            u_apr.id AS aprobador_id,
            u_apr.nombre AS aprobador_nombre,
            collect(DISTINCT pg.id) AS pagos_ids,
            sum(DISTINCT pg.monto) AS total_pagado
        ORDER BY f.id
        """
        with self.driver.session() as session:
            return [record.data() for record in session.run(query)]

    def evaluar_reglas_integridad(self, transacciones: List[Dict[str, Any]]) -> None:
        self.incidencias.clear()
        for tx in transacciones:
            fac_id = tx["factura_id"]
            oc_id = tx["oc_id"]
            rec_id = tx["recepcion_id"]
            fac_monto = tx["factura_monto"] or 0.0
            oc_monto = tx["oc_monto"] or 0.0
            pagos = tx["pagos_ids"] or []

            if not oc_id or not rec_id:
                faltante = "Orden de Compra y Recepción" if not oc_id else "Recepción de Almacén"
                self.incidencias.append(
                    IncidenciaIntegridad(
                        regla_id="R1_THREE_WAY_MATCH",
                        severidad="CRITICA",
                        documento_id=fac_id,
                        tipo_documento="Factura",
                        descripcion=f"Factura {fac_id} carece de {faltante} vinculada.",
                        accion_planificada="RETENER_FACTURA_Y_BLOQUEAR_PAGO",
                        area_escalamiento="Contraloría y Almacén",
                    )
                )

            if oc_id and oc_monto > 0:
                variacion = abs(fac_monto - oc_monto) / oc_monto
                if variacion > self.TOLERANCIA_MONTO_PCT:
                    self.incidencias.append(
                        IncidenciaIntegridad(
                            regla_id="R2_DISCREPANCIA_MONTO",
                            severidad="ALTA",
                            documento_id=fac_id,
                            tipo_documento="Factura",
                            descripcion=(
                                f"Monto de {fac_id} (${fac_monto:,.2f}) difiere en {variacion*100:.1f}% "
                                f"respecto a {oc_id} (${oc_monto:,.2f})."
                            ),
                            accion_planificada="RETENER_POR_DIFERENCIA_PRECIO",
                            area_escalamiento="Gerencia de Compras y CXP",
                        )
                    )

            if tx["creador_id"] and tx["aprobador_id"] and tx["creador_id"] == tx["aprobador_id"]:
                self.incidencias.append(
                    IncidenciaIntegridad(
                        regla_id="R3_VIOLACION_SOD",
                        severidad="CRITICA",
                        documento_id=oc_id,
                        tipo_documento="OrdenCompra",
                        descripcion=(
                            f"Conflicto SoD en {oc_id}: {tx['creador_nombre']} "
                            f"({tx['creador_id']}) creó y aprobó la misma operación."
                        ),
                        accion_planificada="MARCAR_AUDITORIA_INTERNA",
                        area_escalamiento="Auditoría Interna y Dirección Financiera",
                    )
                )

            if len(pagos) > 1:
                self.incidencias.append(
                    IncidenciaIntegridad(
                        regla_id="R4_PAGO_DUPLICADO",
                        severidad="CRITICA",
                        documento_id=fac_id,
                        tipo_documento="Factura",
                        descripcion=(
                            f"Factura {fac_id} con {len(pagos)} pagos asociados "
                            f"({', '.join(pagos)}) por ${tx['total_pagado']:,.2f}."
                        ),
                        accion_planificada="ESCALAR_RECUPERACION_TESORERIA",
                        area_escalamiento="Tesorería y Auditoría Financiera",
                    )
                )

    def ejecutar_plan_acciones(self) -> None:
        timestamp = datetime.now().isoformat(timespec="seconds")
        with self.driver.session() as session:
            session.run("MATCH (a:AlertaAuditoria) DETACH DELETE a")
            for idx, inc in enumerate(self.incidencias, start=1):
                alerta_id = f"ALT-{idx:03d}"
                session.run(
                    """
                    MATCH (doc {id: $doc_id})
                    SET doc.estado = 'RETENIDO_POR_AUDITORIA',
                        doc.ultima_auditoria = $timestamp
                    CREATE (a:AlertaAuditoria {
                        id: $alerta_id,
                        regla: $regla_id,
                        severidad: $severidad,
                        descripcion: $descripcion,
                        accion: $accion,
                        escalado_a: $escalamiento,
                        fecha_deteccion: $timestamp
                    })
                    MERGE (a)-[:AUDITA_A]->(doc)
                    """,
                    doc_id=inc.documento_id,
                    alerta_id=alerta_id,
                    regla_id=inc.regla_id,
                    severidad=inc.severidad,
                    descripcion=inc.descripcion,
                    accion=inc.accion_planificada,
                    escalamiento=inc.area_escalamiento,
                    timestamp=timestamp,
                )

    def generar_reporte_consola(self, total_evaluadas: int) -> None:
        print("=" * 78)
        print("  TRANSACTGUARD AI - REPORTE DE AUDITORÍA DE INTEGRIDAD TRANSACCIONAL")
        print("  Alumno: Oscar Octavio García Maya | Matrícula: 182889")
        print("=" * 78)
        print(f"Transacciones analizadas : {total_evaluadas}")
        print(f"Incidencias detectadas   : {len(self.incidencias)}")
        print("-" * 78)
        for idx, inc in enumerate(self.incidencias, start=1):
            print(f"\n[{idx}] ALERTA {inc.regla_id} | Severidad: {inc.severidad}")
            print(f"    Documento afectado : {inc.tipo_documento} ({inc.documento_id})")
            print(f"    Hallazgo           : {inc.descripcion}")
            print(f"    Acción ejecutada   : {inc.accion_planificada}")
            print(f"    Escalamiento       : {inc.area_escalamiento}")
        print("\n" + "=" * 78)


if __name__ == "__main__":
    NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "12345678")

    agente = TransactGuardAgent(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
    try:
        datos = agente.percibir_ciclo_compras_pagos()
        agente.evaluar_reglas_integridad(datos)
        agente.ejecutar_plan_acciones()
        agente.generar_reporte_consola(len(datos))
    finally:
        agente.cerrar()
