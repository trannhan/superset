# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
import logging
from typing import cast, Optional

from flask_babel import lazy_gettext as _

from superset import security_manager
from superset.charts.commands.exceptions import (
    ChartDeleteFailedError,
    ChartDeleteFailedReportsExistError,
    ChartForbiddenError,
    ChartNotFoundError,
)
from superset.commands.base import BaseCommand
from superset.daos.chart import ChartDAO
from superset.daos.exceptions import DAODeleteFailedError
from superset.daos.report import ReportScheduleDAO
from superset.exceptions import SupersetSecurityException
from superset.models.dashboard import Dashboard
from superset.models.slice import Slice

logger = logging.getLogger(__name__)


class DeleteChartCommand(BaseCommand):
    def __init__(self, model_id: int):
        self._model_id = model_id
        self._model: Optional[Slice] = None

    def run(self) -> None:
        self.validate()
        self._model = cast(Slice, self._model)
        try:
            Dashboard.clear_cache_for_slice(slice_id=self._model_id)
            # Even though SQLAlchemy should in theory delete rows from the association
            # table, sporadically Superset will error because the rows are not deleted.
            # Let's do it manually here to prevent the error.
            self._model.owners = []
            ChartDAO.delete(self._model)
        except DAODeleteFailedError as ex:
            logger.exception(ex.exception)
            raise ChartDeleteFailedError() from ex

    def validate(self) -> None:
        # Validate/populate model exists
        self._model = ChartDAO.find_by_id(self._model_id)
        if not self._model:
            raise ChartNotFoundError()
        # Check there are no associated ReportSchedules
        if reports := ReportScheduleDAO.find_by_chart_id(self._model_id):
            report_names = [report.name for report in reports]
            raise ChartDeleteFailedReportsExistError(
                _("There are associated alerts or reports: %s" % ",".join(report_names))
            )
        # Check ownership
        try:
            security_manager.raise_for_ownership(self._model)
        except SupersetSecurityException as ex:
            raise ChartForbiddenError() from ex
